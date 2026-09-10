from __future__ import annotations

from typing import Any

from .models import TaskRecord
from .security import resolve_inside
from .skills import SkillDefinition
from .tools import ToolRouter


class EvidenceVerifier:
    def __init__(self, router: ToolRouter, skill: SkillDefinition | None):
        self.router = router
        self.skill = skill

    async def evaluate(self, task: TaskRecord) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        acceptance = task.request.acceptance
        for check in acceptance.checks:
            result = await self.router.invoke(
                "run_tests", {"command": check.command, "timeout": 60}
            )
            checks.append({"name": check.name, "layer": check.layer, **result.model_dump()})
        # With no explicit acceptance commands, rerun the latest actual test; never ask a model to grade itself.
        if not acceptance.checks and (not self.skill or "no-write" not in self.skill.verification):
            previous = next(
                (e for e in reversed(task.trace) if e.tool == "run_tests" and e.input and e.result),
                None,
            )
            if previous:
                result = await self.router.invoke("run_tests", previous.input or {})
                checks.append({"name": "repeat-task-tests", "layer": "unit", **result.model_dump()})
            else:
                checks.append(
                    {
                        "name": "test-evidence-required",
                        "layer": "unit",
                        "ok": False,
                        "error": "No acceptance checks or executed tests",
                    }
                )
        diff = await self.router.invoke("git_diff", {})
        task.final_diff = diff.output
        status = await self.router.invoke("git_status", {})
        changed = [line[3:].strip().strip('"') for line in status.output.splitlines()]
        checks.append(
            {
                "name": "diff-review",
                "layer": "repository",
                "ok": diff.ok and (bool(diff.output.strip()) or not acceptance.require_diff),
                "output": diff.output,
                "truncated": diff.truncated,
            }
        )
        for file in acceptance.expected_files:
            checks.append({"name": f"changed:{file}", "layer": "acceptance", "ok": file in changed})
        for file, strings in acceptance.contains.items():
            try:
                content = resolve_inside(self.router.root, file).read_text(encoding="utf-8")
                checks.append(
                    {
                        "name": f"contract:{file}",
                        "layer": "acceptance",
                        "ok": all(s in content for s in strings),
                    }
                )
            except (OSError, ValueError):
                checks.append({"name": f"contract:{file}", "layer": "acceptance", "ok": False})
        requirements = self.skill.verification if self.skill else []
        for requirement in requirements:
            if requirement in {"unit", "syntax", "integration", "repository"}:
                # A diff check alone cannot stand in for a repository-specific executable check.
                passed = any(
                    c.get("layer") == requirement and c.get("ok") and c.get("exit_code") == 0
                    for c in checks
                )
                checks.append({"name": f"skill:{requirement}", "layer": "acceptance", "ok": passed})
            elif requirement == "test-file":
                checks.append(
                    {
                        "name": "skill:test-file",
                        "layer": "acceptance",
                        "ok": any("test" in p for p in changed),
                    }
                )
            elif requirement == "no-write":
                checks.append({"name": "skill:no-write", "layer": "acceptance", "ok": not changed})
        return {
            "passed": all(c.get("ok", False) for c in checks),
            "checks": checks,
            "changed_files": changed,
            "evidence_source": "process-exit-codes-and-file-contracts",
            "model_judge": False,
        }
