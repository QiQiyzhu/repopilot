from __future__ import annotations

import asyncio
import io
import re
import stat
import zipfile
from pathlib import Path

from .security import BoundaryError, child_environment, resolve_inside, run_process


class GitWorkspace:
    """Materialize a committed Git archive, never execute source hooks or copy credentials."""

    def __init__(self, root: Path, repository_root: Path):
        self.root = root.resolve()
        self.repository_root = repository_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def validate_repository(self, repository: str) -> Path:
        source = Path(repository).resolve()
        if not source.is_relative_to(self.repository_root) or not source.is_dir():
            raise BoundaryError("Repository must be under configured REPOPILOT_REPO_ROOT")
        return source

    async def create(self, repository: str, ref: str, task_id: str) -> tuple[str, str]:
        source = self.validate_repository(repository)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./~-]{0,199}", ref) or ".." in ref:
            raise BoundaryError("Invalid repository ref")
        if not re.fullmatch(r"[a-f0-9-]{36}", task_id):
            raise BoundaryError("Invalid task identifier")
        resolved = await run_process(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], source)
        if not resolved.ok:
            raise BoundaryError("Repository/ref is not a committed Git revision")
        sha = resolved.output.strip()
        target = self.root / task_id
        target.mkdir(exist_ok=False)
        process = await asyncio.create_subprocess_exec(
            "git",
            "archive",
            "--format=zip",
            sha,
            cwd=source,
            env=child_environment(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            payload, stderr = await asyncio.wait_for(process.communicate(), 30)
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode:
            raise BoundaryError(f"git archive failed: {stderr.decode(errors='replace')[:200]}")
        if len(payload) > 100_000_000:
            raise BoundaryError("Repository archive exceeds 100 MB limit")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            total = 0
            for member in archive.infolist():
                if member.is_dir():
                    continue
                if member.filename.split("/")[0] == ".git" or any(
                    x.startswith(".env") for x in member.filename.split("/")
                ):
                    continue
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise BoundaryError("Repository symlinks require a stronger sandbox")
                total += member.file_size
                if total > 200_000_000:
                    raise BoundaryError("Expanded archive exceeds 200 MB limit")
                path = resolve_inside(target, member.filename)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(member))
        for args in (
            ["init", "--quiet"],
            ["add", "--all"],
            [
                "-c",
                "user.name=RepoPilot",
                "-c",
                "user.email=repopilot@localhost",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.hooksPath=" + str(target / ".no-hooks"),
                "commit",
                "--quiet",
                "-m",
                "Workspace baseline",
            ],
        ):
            result = await run_process(["git", *args], target)
            if not result.ok:
                raise BoundaryError(f"Workspace initialization failed: {result.output}")
        return str(target), sha
