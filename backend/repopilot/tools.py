from __future__ import annotations

import difflib
import json
import re
import time
from pathlib import Path
from typing import Any

from .models import ToolResult
from .security import (
    BoundaryError,
    redact,
    resolve_inside,
    run_process,
    validate_command,
    visible_files,
)

NATIVE_TO_MCP = {
    "search_code": "repo.search",
    "read_file": "repo.read",
    "run_tests": "tests.run",
    "git_diff": "git.diff",
}
TOOL_NAMES = [
    "read_file",
    "list_files",
    "search_code",
    "read_symbol",
    "apply_patch",
    "git_diff",
    "git_status",
    "run_tests",
    "run_command_safe",
]


class ToolRouter:
    def __init__(
        self,
        root: Path,
        *,
        allow_repository_code: bool = False,
        allowed_tools: list[str] | None = None,
    ):
        self.root = root.resolve()
        self.allow_repository_code = allow_repository_code
        self.allowed_tools = allowed_tools if allowed_tools is not None else TOOL_NAMES
        self.approved_deletions: set[str] = set()
        self.pending_deletion: str | None = None

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        started = time.monotonic()
        try:
            if name not in self.allowed_tools:
                raise BoundaryError(f"Tool {name} is denied by selected skill")
            result = await self._invoke(name, arguments)
        except (ValueError, OSError, TypeError, KeyError) as error:
            result = ToolResult(ok=False, error=redact(str(error)))
        result.output = redact(result.output)
        result.duration_ms = (time.monotonic() - started) * 1000
        return result

    def _read(self, path: str) -> str:
        target = resolve_inside(self.root, path)
        if target.stat().st_size > 1_000_000:
            raise BoundaryError("File exceeds 1 MB read limit")
        return target.read_text(encoding="utf-8")

    async def _invoke(self, name: str, args: dict[str, Any]) -> ToolResult:
        if name == "list_files":
            return ToolResult(ok=True, output="\n".join(visible_files(self.root)))
        if name == "read_file":
            content = self._read(args["path"])
            start = max(1, int(args.get("start_line", 1)))
            count = min(300, max(1, int(args.get("line_count", 180))))
            lines = content.splitlines()
            return ToolResult(
                ok=True,
                output="\n".join(
                    f"{i + 1}: {line}"
                    for i, line in enumerate(lines)
                    if start - 1 <= i < start - 1 + count
                ),
                truncated=len(lines) > start - 1 + count,
            )
        if name in {"search_code", "read_symbol"}:
            query = str(args.get("query", args.get("symbol", "")))
            if not query or len(query) > 200:
                raise BoundaryError("Search query must contain 1–200 characters")
            matches = []
            for path in visible_files(self.root):
                try:
                    content = self._read(path)
                except (UnicodeError, OSError, BoundaryError):
                    continue
                for i, line in enumerate(content.splitlines()):
                    match = query.lower() in line.lower()
                    if name == "read_symbol":
                        match = bool(
                            re.search(
                                r"\b(?:def|class|function|const|interface)\s+"
                                + re.escape(query)
                                + r"\b",
                                line,
                            )
                        )
                    if match:
                        matches.append({"path": path, "line": i + 1, "text": line[:500]})
                    if len(matches) >= 60:
                        return ToolResult(ok=True, output=json.dumps(matches), truncated=True)
            return ToolResult(ok=True, output=json.dumps(matches))
        if name == "apply_patch":
            path = str(args["path"])
            target = resolve_inside(self.root, path)
            original = target.read_bytes().decode("utf-8") if target.exists() else ""
            newline = "\r\n" if "\r\n" in original else "\n"
            old = original.replace("\r\n", "\n")
            if len(old) > 1_000_000:
                raise BoundaryError("File exceeds patch limit")
            if args.get("delete"):
                if path not in self.approved_deletions:
                    self.pending_deletion = path
                    return ToolResult(
                        ok=False,
                        requires_approval=True,
                        error="Deletion requires explicit task approval",
                        output=path,
                    )
                self.approved_deletions.remove(path)
                target.unlink()
                new = ""
            else:
                before = str(args.get("old", "")).replace("\r\n", "\n")
                after = str(args.get("new", "")).replace("\r\n", "\n")
                if len(after) > 200_000:
                    raise BoundaryError("Patch exceeds 200 KB limit")
                if target.exists():
                    if not before or old.count(before) != 1:
                        raise BoundaryError(
                            "Patch old text must match exactly once; read file first"
                        )
                    new = old.replace(before, after, 1)
                else:
                    if before:
                        raise BoundaryError("Cannot match old text in a new file")
                    new = after
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(new.replace("\n", newline).encode("utf-8"))
            diff = "".join(
                difflib.unified_diff(
                    old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}"
                )
            )
            return ToolResult(ok=True, output=diff[:16000], truncated=len(diff) > 16000)
        if name in {"git_diff", "git_status"}:
            command = (
                ["git", "diff", "--no-ext-diff", "--no-color"]
                if name == "git_diff"
                else ["git", "status", "--short"]
            )
            result = await run_process(
                validate_command(command, self.root, self.allow_repository_code), self.root
            )
            if name == "git_diff":
                # git diff omits new untracked files, so make additions reviewable without staging them.
                status = await run_process(
                    ["git", "ls-files", "--others", "--exclude-standard"], self.root
                )
                additions = []
                for path in status.output.splitlines()[:100]:
                    try:
                        text = self._read(path)
                        additions.append(
                            "".join(
                                difflib.unified_diff(
                                    [], text.splitlines(True), "/dev/null", f"b/{path}"
                                )
                            )
                        )
                    except (UnicodeError, BoundaryError, OSError):
                        continue
                output = result.output + "\n".join(additions)
                result.output = output[:64000]
                result.truncated |= len(output) > 64000
            return result
        if name in {"run_tests", "run_command_safe"}:
            command = args.get("command", ["python", "-m", "pytest", "-q"])
            if not isinstance(command, list):
                raise BoundaryError("command must be an argument array")
            cwd = resolve_inside(self.root, str(args.get("cwd", ".")), allow_root=True)
            return await run_process(
                validate_command(command, self.root, self.allow_repository_code),
                cwd,
                timeout=min(60, max(0.1, float(args.get("timeout", 30)))),
            )
        raise BoundaryError("Unknown tool")
