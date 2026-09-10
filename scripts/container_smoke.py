"""Exercise the built Nginx/API/MCP stack through its published HTTP port.

Uses only the Python standard library so the CI host cannot accidentally supply
application dependencies that are absent from the backend image. Every response
and assertion is retained as evidence, including failure responses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

TERMINAL = {"succeeded", "failed", "cancelled", "timed_out", "unverified"}


class ContainerProbe:
    def __init__(self, base: str, output: Path, timeout: float, resume: bool = False):
        self.base = base.rstrip("/")
        self.output = output
        self.timeout = timeout
        self.resume = resume
        self.output.mkdir(parents=True, exist_ok=True)
        self.checks: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        self.started = time.monotonic()
        self.task_id: str | None = None

    def save(self, name: str, value: Any) -> None:
        (self.output / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def require(self, name: str, condition: bool, detail: Any = None) -> None:
        self.checks.append({"name": name, "passed": bool(condition), "detail": detail})
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    def request(
        self, path: str, name: str, body: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        url = urljoin(self.base + "/", path.lstrip("/"))
        headers = {"Origin": self.base}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = Request(url, headers=headers, data=data)
        began = time.monotonic()
        try:
            response = urlopen(request, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            payload = response.read(5_000_001)
            status = response.status
            response_headers = dict(response.headers.items())
        (self.output / name).write_bytes(payload)
        self.responses.append(
            {
                "url": url,
                "method": "POST" if body is not None else "GET",
                "status": status,
                "headers": response_headers,
                "body_file": name,
                "bytes": len(payload),
                "duration_ms": round((time.monotonic() - began) * 1000, 2),
            }
        )
        self.require("response size bounded", len(payload) <= 5_000_000, name)
        return status, response_headers, payload

    def get_json(self, path: str, name: str, expected: int = 200, body: Any = None) -> Any:
        status, _, payload = self.request(path, name, body)
        self.require(f"{path} returns {expected}", status == expected, status)
        return json.loads(payload)

    def wait_health(self) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        errors = []
        while time.monotonic() < deadline:
            try:
                status, headers, payload = self.request("api/health", "health.json")
                health = json.loads(payload)
                if status == 200 and health.get("status") == "ok":
                    self.require(
                        "API is reached through Nginx",
                        "nginx" in headers.get("Server", "").lower(),
                        headers.get("Server"),
                    )
                    self.require(
                        "container workspace root",
                        health.get("repository_root") == "/workspace",
                        health,
                    )
                    self.require(
                        "known demo repository exists",
                        str(health.get("demo_repository", "")).startswith("/workspace/"),
                        health,
                    )
                    self.save("health-wait-errors.json", errors)
                    return health
                errors.append({"status": status, "body": payload.decode(errors="replace")})
            except (URLError, OSError, ValueError) as error:
                errors.append({"error": str(error)})
            time.sleep(1)
        self.save("health-wait-errors.json", errors)
        raise TimeoutError("Container proxy/API did not become healthy before the deadline")

    def frontend(self) -> None:
        status, headers, payload = self.request("/", "frontend.html")
        html = payload.decode()
        self.require("frontend HTML served", status == 200 and 'id="root"' in html, headers)
        scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
        self.require("production JS asset referenced", bool(scripts), scripts)
        for index, script in enumerate(scripts):
            parsed = urlsplit(script)
            self.require("frontend asset is local", not parsed.netloc and not parsed.scheme, script)
            asset_status, asset_headers, asset = self.request(script, f"frontend-{index}.js")
            content_type = asset_headers.get("Content-Type", "")
            self.require(
                "JS asset is actual JavaScript, not SPA fallback",
                asset_status == 200 and "javascript" in content_type and len(asset) > 100,
                content_type,
            )

    def task(self, health: dict[str, Any]) -> dict[str, Any]:
        if self.resume:
            created = json.loads((self.output / "created-task.json").read_text(encoding="utf-8"))
        else:
            request = {
                "repository": health["demo_repository"],
                "task": "Fix clamp so interior and both boundary cases pass",
                "provider": "fake",
                "transport": "mcp",
                "allow_repository_code": True,
                "budget": {"timeout_seconds": 120, "max_steps": 12},
                "acceptance": {
                    "checks": [
                        {
                            "name": "container-clamp-tests",
                            "command": ["python", "-m", "pytest", "-q", "test_calculator.py"],
                            "layer": "unit",
                        }
                    ],
                    "expected_files": ["calculator.py"],
                    "contains": {"calculator.py": ["return max(low, min(high, value))"]},
                    "require_diff": True,
                },
            }
            self.save("submitted-request.json", request)
            created = self.get_json("api/tasks", "created-task.json", 202, request)
        self.task_id = created["task_id"]
        deadline = time.monotonic() + self.timeout
        polls = []
        while time.monotonic() < deadline:
            task = self.get_json(
                f"api/tasks/{self.task_id}", "restarted-task.json" if self.resume else "task.json"
            )
            polls.append(
                {"status": task["status"], "state": task["state"], "step_count": task["step_count"]}
            )
            if task["status"] in TERMINAL:
                self.save("restart-polls.json" if self.resume else "task-polls.json", polls)
                return task
            time.sleep(0.5)
        self.save("task-polls.json", polls)
        raise TimeoutError(f"Task {self.task_id} did not finish")

    def verify(self, task: dict[str, Any]) -> None:
        self.require("task succeeded", task["status"] == "succeeded", task.get("error"))
        result = task.get("test_result") or {}
        self.require(
            "executable verifier passed",
            result.get("passed") is True and result.get("model_judge") is False,
            result,
        )
        checks = result.get("checks", [])
        self.require(
            "container pytest acceptance actually executed",
            any(
                c.get("name") == "container-clamp-tests"
                and c.get("exit_code") == 0
                and "3 passed" in c.get("output", "")
                for c in checks
            ),
            checks,
        )
        self.require(
            "all acceptance checks passed", bool(checks) and all(c.get("ok") for c in checks)
        )
        diff = task.get("final_diff", "")
        if self.resume:
            self.require(
                "diff survives backend restart unchanged",
                diff == (self.output / "change.patch").read_text(encoding="utf-8"),
            )
        (self.output / ("restarted.patch" if self.resume else "change.patch")).write_text(
            diff, encoding="utf-8"
        )
        self.require(
            "exact repair in final diff",
            "-    return max(low, max(high, value))" in diff
            and "+    return max(low, min(high, value))" in diff,
            diff,
        )
        self.require(
            "only intended file changed",
            result.get("changed_files") == ["calculator.py"],
            result.get("changed_files"),
        )
        trace = task.get("trace", [])
        mcp = [e for e in trace if e.get("kind") == "tool" and e.get("transport") == "mcp"]
        self.require(
            "real MCP read and diff succeeded",
            all(
                any(e.get("tool") == name and (e.get("result") or {}).get("ok") for e in mcp)
                for name in ("read_file", "git_diff")
            ),
        )
        tests = [e for e in mcp if e.get("tool") == "run_tests"]
        self.require(
            "MCP reproduced failing tests before successful repair",
            any((e.get("result") or {}).get("exit_code") == 1 for e in tests)
            and any((e.get("result") or {}).get("exit_code") == 0 for e in tests),
        )
        self.require(
            "fake provenance remains explicit",
            task.get("evidence_label") == "harness-demonstration"
            and task["request"]["provider"] == "fake",
        )
        listing = self.get_json(
            "api/tasks", "restart-task-list.json" if self.resume else "task-list.json"
        )
        self.require(
            "persisted task appears in API list",
            any(t["task_id"] == self.task_id and t["status"] == "succeeded" for t in listing),
        )
        status, headers, payload = self.request(
            f"api/tasks/{self.task_id}/events",
            "restart-events.sse" if self.resume else "events.sse",
        )
        self.require(
            "SSE passes through reverse proxy",
            status == 200
            and "text/event-stream" in headers.get("Content-Type", "")
            and b"event: trace" in payload
            and b"event: done" in payload,
        )
        self.get_json(f"api/tasks/{self.task_id}/context", "context.json")
        skills = self.get_json("api/skills", "skills.json")
        self.require("packaged skills loaded inside image", bool(skills))

    def run(self) -> None:
        error = None
        try:
            health = self.wait_health()
            self.frontend()
            task = self.task(health)
            self.verify(task)
        except Exception as caught:
            error = repr(caught)
            raise
        finally:
            report = {
                "status": "passed" if error is None else "failed",
                "phase": "after-backend-restart" if self.resume else "fresh-compose-startup",
                "source": "Actual HTTP requests through built Nginx and FastAPI containers",
                "provider": "deterministic-fake; harness validation, not LLM performance",
                "created_at": datetime.now(UTC).isoformat(),
                "commit": os.environ.get("GITHUB_SHA"),
                "ci_run_id": os.environ.get("GITHUB_RUN_ID"),
                "base_url": self.base,
                "task_id": self.task_id,
                "elapsed_ms": round((time.monotonic() - self.started) * 1000, 2),
                "checks": self.checks,
                "responses": self.responses,
                "error": error,
            }
            diff_path = self.output / ("restarted.patch" if self.resume else "change.patch")
            if diff_path.exists():
                report["diff_sha256"] = hashlib.sha256(diff_path.read_bytes()).hexdigest()
            self.save("restart-summary.json" if self.resume else "summary.json", report)
            print(json.dumps({k: report[k] for k in ("status", "phase", "task_id", "error")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", type=Path, default=Path("outputs/container"))
    parser.add_argument("--timeout", type=float, default=150)
    parser.add_argument(
        "--resume", action="store_true", help="Verify the same saved task after a backend restart"
    )
    args = parser.parse_args()
    ContainerProbe(args.base_url, args.output, args.timeout, args.resume).run()
