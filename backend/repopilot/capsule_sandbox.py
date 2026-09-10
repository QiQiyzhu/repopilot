"""Restricted execution for authored Python capsules; no trusted-host fallback.

Only three freshly copied files can enter a container. The controller owns the
oracle and compares results outside the candidate process. This is a Docker
boundary for this narrow pack, not a general hostile multi-tenant service.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import ToolResult
from .security import child_environment
from .tools import ToolRouter

VISIBLE_COMMAND = ["python", "-m", "unittest", "-q", "test_visible"]
GATEWAY = """import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('candidate', '/work/solution.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
inputs = json.loads(sys.stdin.read())
outputs = []
for item in inputs:
    before = json.dumps(item)
    value = module.solve(item)
    outputs.append({'value': value, 'input_unchanged': before == json.dumps(item)})
print(json.dumps(outputs, allow_nan=False, separators=(',', ':')))
"""


class SandboxUnavailable(RuntimeError):
    pass


class DockerSandbox:
    def __init__(self, image: str, staging: Path, *, timeout: float = 12):
        # Require a local immutable image ID, never resolve a mutable remote tag at run time.
        if not image.startswith("sha256:") or len(image) != 71:
            raise ValueError("Use the inspected immutable local Docker image ID")
        self.image, self.staging, self.timeout = image, staging.resolve(), timeout
        self.staging.mkdir(parents=True, exist_ok=True)
        self.calls = 0

    def command(self, name: str, mount: Path, *, visible: bool) -> list[str]:
        return [
            "docker", "run", "--rm", "--name", name, "--pull=never", "--network=none",
            "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
            "--user=65534:65534", "--pids-limit=32", "--memory=128m", "--memory-swap=128m",
            "--cpus=0.5", "--ulimit=nofile=64:64", "--log-driver=none",
            "--mount", f"type=bind,src={mount},dst=/work,readonly",
            "--workdir=/work", "--env=PYTHONDONTWRITEBYTECODE=1", "--interactive",
            self.image, "python", "-B",
            *(["-m", "unittest", "-q", "test_visible"] if visible else ["-I", "/work/gateway.py"]),
        ]

    async def preflight(self) -> dict[str, Any]:
        if shutil.which("docker") is None:
            raise SandboxUnavailable("Docker is required; host execution is forbidden")
        process = await asyncio.create_subprocess_exec(
            "docker", "image", "inspect", self.image, "--format", "{{json .}}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=child_environment(),
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), 15)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise SandboxUnavailable("Docker image inspection timed out") from None
        if process.returncode:
            raise SandboxUnavailable("The frozen Docker image is not available locally")
        info = json.loads(stdout)
        if info.get("Id") != self.image or info.get("Os") != "linux":
            raise SandboxUnavailable("A matching Linux Docker image is required")
        return {key: info.get(key) for key in ["Id", "RepoDigests", "Architecture", "Os"]}

    async def execute(
        self, code: str, *, visible_tests: str | None = None, inputs: list[Any] | None = None
    ) -> ToolResult:
        started = time.monotonic()
        if len(code.encode()) > 200_000:
            return ToolResult(ok=False, error="candidate_too_large")
        self.calls += 1
        name = "repopilot-capsule-" + uuid4().hex
        limit = 65536
        with tempfile.TemporaryDirectory(prefix="candidate-", dir=self.staging) as folder:
            mount = Path(folder)
            mount.chmod(0o755)
            # Never mount the actor repository, .git, oracle, host root or API environment.
            for filename, content in {
                "solution.py": code,
                "test_visible.py": visible_tests or "",
                "gateway.py": GATEWAY,
            }.items():
                target = mount / filename
                target.write_text(content, encoding="utf-8")
                target.chmod(0o444)
            command = self.command(name, mount, visible=visible_tests is not None)
            try:
                process = await asyncio.create_subprocess_exec(
                    *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE, env=child_environment(),
                )
            except OSError:
                return ToolResult(ok=False, error="sandbox_start_failed")

            async def bounded_read(stream: asyncio.StreamReader) -> bytes:
                chunks = bytearray()
                while chunk := await stream.read(4096):
                    chunks.extend(chunk)
                    if len(chunks) > limit:
                        raise ValueError("sandbox_output_limit")
                return bytes(chunks)

            async def communicate() -> tuple[bytes, bytes]:
                assert process.stdin and process.stdout and process.stderr
                process.stdin.write(json.dumps(inputs or []).encode())
                await process.stdin.drain()
                process.stdin.close()
                readers = [
                    asyncio.create_task(bounded_read(process.stdout)),
                    asyncio.create_task(bounded_read(process.stderr)),
                ]
                try:
                    result = await asyncio.gather(*readers)
                    await process.wait()
                    return result[0], result[1]
                finally:
                    for reader in readers:
                        if not reader.done():
                            reader.cancel()
                    await asyncio.gather(*readers, return_exceptions=True)

            result = ToolResult(ok=False, error="sandbox_interrupted")
            try:
                stdout, stderr = await asyncio.wait_for(communicate(), self.timeout)
                output = stdout.decode("utf-8", errors="replace")
                if visible_tests is not None:
                    output += stderr.decode("utf-8", errors="replace")
                result = ToolResult(
                    ok=process.returncode == 0, exit_code=process.returncode,
                    output=output, error=None if process.returncode == 0 else "candidate_process_failed",
                )
            except TimeoutError:
                result = ToolResult(ok=False, error="sandbox_timeout")
            except (ValueError, BrokenPipeError, ConnectionResetError):
                result = ToolResult(ok=False, error="sandbox_output_or_protocol_limit", truncated=True)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                # Cancelling the Docker client does not reliably stop its container.
                # Remove only this UUID-owned container, including on outer cancellation.
                cleanup = await asyncio.create_subprocess_exec(
                    "docker", "rm", "--force", name,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    env=child_environment(),
                )
                try:
                    await asyncio.wait_for(cleanup.wait(), 10)
                except TimeoutError:
                    cleanup.kill()
                    await cleanup.wait()
                    result = ToolResult(ok=False, error="sandbox_cleanup_timeout")
            result.duration_ms = round((time.monotonic() - started) * 1000, 3)
            return result


class CapsuleRouter(ToolRouter):
    def __init__(self, root: Path, allowed: list[str] | None, sandbox: DockerSandbox):
        super().__init__(root, allowed_tools=allowed, allow_repository_code=False)
        self.sandbox = sandbox

    async def _invoke(self, name: str, args: dict[str, Any]) -> ToolResult:
        if name == "apply_patch" and (args.get("path") != "solution.py" or args.get("delete")):
            return ToolResult(ok=False, error="capsule_only_solution_py_is_writable")
        if name == "run_tests":
            if args.get("command") != VISIBLE_COMMAND:
                return ToolResult(ok=False, error="capsule_requires_exact_visible_test_command")
            return await self.sandbox.execute(
                (self.root / "solution.py").read_text(encoding="utf-8"),
                visible_tests=(self.root / "test_visible.py").read_text(encoding="utf-8"),
            )
        if name == "run_command_safe":
            return ToolResult(ok=False, error="capsule_shell_execution_forbidden")
        return await super()._invoke(name, args)
