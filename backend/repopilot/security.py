from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import time
from pathlib import Path
from typing import Any

from .models import ToolResult

SENSITIVE = {".git", ".env", ".ssh", ".aws", ".azure", ".gnupg", "node_modules", ".venv"}
SECRET_PATTERNS = [
    re.compile(r"(?i)(?:sk-[a-zA-Z0-9_-]{12,}|gh[pousr]_[a-zA-Z0-9_]{12,})"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret|authorization)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(Bearer\s+)[a-zA-Z0-9._-]+"),
]


def redact(value: str) -> str:
    for pattern in SECRET_PATTERNS:
        value = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", value)
    return value


def redact_data(value: Any) -> Any:
    """Redact leaves, not serialized JSON; removing a secret must not corrupt its envelope."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: redact_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    return value


class BoundaryError(ValueError):
    pass


def resolve_inside(root: Path, relative: str, *, allow_root: bool = False) -> Path:
    if not relative or any(char in relative for char in "\x00\r\n:"):
        raise BoundaryError("Invalid path or alternate data stream")
    normalized = relative.replace("\\", "/")
    if any(
        part == ".." or part in SENSITIVE or part.startswith(".env")
        for part in normalized.split("/")
    ):
        raise BoundaryError("Path traversal or protected path denied")
    path = root / normalized
    if Path(normalized).is_absolute() or path.is_symlink():
        raise BoundaryError("Absolute paths and symlinks are denied")
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()) or (
        resolved == root.resolve() and not allow_root
    ):
        raise BoundaryError("Path is outside workspace")
    # Check every ancestor, including links that resolve back inside the workspace.
    for parent in [path, *path.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise BoundaryError("Symlink traversal denied")
    return resolved


def visible_files(root: Path, limit: int = 3000) -> list[str]:
    result: list[str] = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in SENSITIVE
            and not d.startswith(".")
            and not (Path(directory) / d).is_symlink()
            and d not in {"dist", "build", "__pycache__"}
        )
        for name in sorted(files):
            if name.startswith(".env"):
                continue
            path = Path(directory) / name
            if path.is_symlink():
                continue
            result.append(path.relative_to(root).as_posix())
            if len(result) >= limit:
                return result
    return result


def validate_command(command: list[str], root: Path, allow_repository_code: bool) -> list[str]:
    if not command or any(
        not isinstance(x, str) or any(c in x for c in "\x00\r\n;&|><`") for x in command
    ):
        raise BoundaryError("Shell syntax is not allowed; pass an argument array")
    executable = command[0]
    if executable not in {"git", "python", "node", "npm"}:
        raise BoundaryError("Executable is not allowlisted")
    args = command[1:]
    if executable == "git":
        if args not in (
            ["status", "--short"],
            ["diff", "--no-ext-diff", "--no-color"],
            ["diff", "--stat"],
            ["diff", "--check"],
        ):
            raise BoundaryError("Only read-only git status/diff is allowed")
    elif executable == "node":
        if args != ["--version"]:
            raise BoundaryError("Arbitrary Node execution is denied")
    elif executable == "npm":
        if (
            len(args) != 2
            or args[0] != "run"
            or args[1] not in {"test", "typecheck", "lint", "build", "test:simulation"}
        ):
            raise BoundaryError("Only named repository checks are allowed")
    elif executable == "python":
        if len(args) < 2 or args[:2] not in (["-m", "pytest"], ["-m", "compileall"]):
            raise BoundaryError("Only Python pytest/compileall is allowed")
        for arg in args[2:]:
            if arg.startswith("-"):
                if arg not in {"-q", "-x", "--disable-warnings", "--maxfail=1"}:
                    raise BoundaryError("Unapproved Python check option")
            else:
                resolve_inside(root, arg.split("::")[0], allow_root=True)
    if executable in {"python", "npm"} and not allow_repository_code:
        raise BoundaryError(
            "Repository tests execute code. Set allow_repository_code only for a repository you trust, or use an OS/container sandbox"
        )
    # npm.cmd requires cmd.exe on Windows; resolve its JS entrypoint and run Node directly.
    if executable == "npm" and os.name == "nt":
        npm = shutil.which("npm.cmd")
        if not npm:
            raise BoundaryError("npm unavailable")
        entry = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
        if not entry.exists():
            raise BoundaryError("Cannot resolve npm CLI safely")
        return [shutil.which("node") or "node", str(entry), *args]
    if executable == "python":
        import sys

        return [sys.executable, *args]
    return [shutil.which(executable) or executable, *args]


def child_environment() -> dict[str, str]:
    keep = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "LANG",
        "LC_ALL",
        "PATHEXT",
    }
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env.update(
        {
            "CI": "1",
            "NO_COLOR": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
    )
    return env


async def kill_process_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)  # type: ignore[attr-defined]
        except ProcessLookupError:
            pass
    await process.wait()


async def run_process(
    command: list[str],
    cwd: Path,
    timeout: float = 30,
    output_limit: int = 16000,
    *,
    env: dict[str, str] | None = None,
) -> ToolResult:
    """No shell. Output is drained incrementally and bounded even for a noisy child."""
    started = time.monotonic()
    kwargs: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {}
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        env=env or child_environment(),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        **kwargs,
    )
    chunks: list[bytes] = []
    size = 0
    truncated = False

    async def drain() -> None:
        nonlocal size, truncated
        assert process.stdout
        while chunk := await process.stdout.read(4096):
            available = max(0, output_limit - size)
            chunks.append(chunk[:available]) if available else None
            truncated |= len(chunk) > available
            size += min(len(chunk), available)
        await process.wait()

    try:
        await asyncio.wait_for(drain(), timeout)
    except TimeoutError:
        await kill_process_tree(process)
        return ToolResult(
            ok=False,
            error="command_timeout",
            output=redact(b"".join(chunks).decode(errors="replace")),
            truncated=truncated,
            duration_ms=(time.monotonic() - started) * 1000,
        )
    except asyncio.CancelledError:
        await kill_process_tree(process)
        raise
    return ToolResult(
        ok=process.returncode == 0,
        output=redact(b"".join(chunks).decode(errors="replace")),
        exit_code=process.returncode,
        truncated=truncated,
        duration_ms=(time.monotonic() - started) * 1000,
    )
