"""Execute an authored counterexample to equating green tests with task completion.

Uses the existing verifier, pinned ARC contract and mutation. No model is invoked.
The command is an operator-owned experiment for trusted code, not an agent tool.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from .evaluation import ROOT, acceptance, apply_reference, contract_rejected
from .models import Acceptance, Budget, Check, TaskRecord, TaskRequest, now
from .security import child_environment, resolve_inside, run_process
from .skills import SkillRegistry
from .tools import ToolRouter
from .verifier import EvidenceVerifier
from .workspace import GitWorkspace

TASK_ID = "arc-017-test-distance"
WEAK_TEST = """import { test } from 'vitest';
import assert from 'node:assert/strict';
import { distance } from '../src/core/math';
test('distance along an axis and at the same point', () => {
  assert.equal(distance({x:0,y:0},{x:3,y:0}),3);
  assert.equal(distance({x:2,y:2},{x:2,y:2}),0);
});
"""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decide(baseline: dict[str, Any], mutated: dict[str, Any]) -> dict[str, Any]:
    """Case-specific oracle, not a general proof of candidate-test correctness."""
    killed = contract_rejected(mutated) and "7 !== 5" in mutated.get("output", "")
    return {
        "accepted": bool(baseline.get("passed") and killed),
        "mutation_killed": killed,
        "reason": "diagonal-regression-detected" if killed else "supplied-mutation-not-detected",
    }


async def run_case(repository: Path, data: Path, output: Path) -> dict[str, Any]:
    repository, data = repository.resolve(), data.resolve()
    manifest_path = ROOT / "evaluation/tasks/arc-shift.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract = next(t for t in manifest["tasks"] if t["task_id"] == TASK_ID)
    task_data = data / str(uuid4())
    task_data.mkdir(parents=True)
    factory = GitWorkspace(task_data / "workspaces", repository.parent)
    workspace_name, source_sha = await factory.create(
        str(repository), manifest["repository_commit"], str(uuid4())
    )
    workspace = Path(workspace_name)
    # Dependency installation is an explicit trusted-operator setup step, never
    # added to ToolRouter's model-facing allowlist. No install scripts run.
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise RuntimeError("npm is required; run npm ci --prefix evaluation --ignore-scripts first")
    command = [npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"]
    if os.name == "nt":
        command = [
            shutil.which("node") or "node",
            str(Path(npm).parent / "node_modules/npm/bin/npm-cli.js"),
            *command[1:],
        ]
    env = child_environment()
    env["npm_config_cache"] = str(data / "npm-cache")
    installed = await run_process(command, workspace, timeout=300, env=env)
    if not installed.ok:
        raise RuntimeError(f"Pinned dependency installation failed: {installed.output}")

    skill = SkillRegistry(ROOT / "skills").get("add-unit-test")
    assert skill is not None
    router = ToolRouter(workspace, allow_repository_code=True, allowed_tools=skill.allowed_tools)
    mutation = contract["adequacy_mutation"]
    implementation = resolve_inside(workspace, mutation["path"])
    original = implementation.read_bytes()
    candidate_path = contract["reference_patch"]["path"]
    candidates = [("axis-only", WEAK_TEST), ("diagonal-reference", contract["reference_patch"]["new"])]
    rows = []
    previous = ""
    for candidate_id, candidate in candidates:
        patch = await router.invoke(
            "apply_patch", {"path": candidate_path, "old": previous, "new": candidate}
        )
        if not patch.ok:
            raise RuntimeError(f"Candidate patch failed: {patch.error}")
        previous = candidate
        request = TaskRequest(
            repository=str(repository),
            task=contract["description"],
            ref=source_sha,
            skill="add-unit-test",
            memory_enabled=False,
            allow_repository_code=True,
            acceptance=Acceptance(
                checks=[Check(name="full-pinned-regression", command=["npm", "run", "test"])],
                expected_files=contract["required_files"],
            ),
        )
        record = TaskRecord(
            task_id=str(uuid4()), repository=str(repository), request=request, budget=Budget()
        )
        in_loop = await EvidenceVerifier(router, skill).evaluate(record)
        baseline = await acceptance(workspace, contract, task_data)
        try:
            apply_reference(workspace, mutation)
            mutated = await acceptance(workspace, contract, task_data)
        finally:
            implementation.write_bytes(original)
        restored = implementation.read_bytes() == original
        full_regression = next(c for c in in_loop["checks"] if c["name"] == "full-pinned-regression")
        count = re.search(r"Tests\s+(\d+) passed", full_regression.get("output", ""))
        rows.append(
            {
                "id": candidate_id,
                "authorship": "AI-assisted authored candidate; no model provider called",
                "candidate_source": candidate,
                "candidate_sha256": _digest(candidate.encode()),
                "in_loop_verifier": in_loop,
                "regression_tests_passed": int(count[1]) if count else None,
                "independent_baseline": baseline,
                "independent_mutant": mutated,
                "final_decision": decide(baseline, mutated),
                "implementation_restored": restored,
                "implementation_sha256_after": _digest(implementation.read_bytes()),
            }
        )
    proven = (
        all(r["in_loop_verifier"]["passed"] and r["implementation_restored"] for r in rows)
        and all(r["independent_baseline"]["passed"] for r in rows)
        and rows[0]["independent_mutant"]["passed"]
        and not rows[0]["final_decision"]["accepted"]
        and rows[1]["final_decision"]["accepted"]
        and all(r["in_loop_verifier"]["changed_files"] == [candidate_path] for r in rows)
    )
    revision = await run_process(["git", "rev-parse", "HEAD"], ROOT)
    dirty = await run_process(["git", "status", "--porcelain"], ROOT)
    report = {
        "id": "repopilot-green-tests-counterexample",
        "title": "Tests passed. Did the requested regression test actually protect the behavior?",
        "recorded_at": now(),
        "case_proven": bool(proven),
        "evidence_type": "authored-candidate-and-reference-process-controls",
        "is_model_benchmark": False,
        "provider_invocations": 0,
        "fake_provider_invocations": 0,
        "real_model_runs": 0,
        "model_performance": None,
        "decision_prompt": "Both candidates pass the entire regression suite. Accept both, or require evidence that each new test rejects the specified defect?",
        "task_id": TASK_ID,
        "repository": manifest["tasks"][0]["repository"],
        "repository_commit": source_sha,
        "harness_commit_at_execution": revision.output.strip(),
        "harness_worktree_dirty_at_execution": bool(dirty.output.strip()),
        "environment": {"python": platform.python_version(), "platform": platform.system()},
        "source_hashes": {
            "task_manifest_sha256": _digest(manifest_path.read_bytes()),
            "runner_sha256": _digest(Path(__file__).read_bytes()),
            "independent_evaluator_sha256": _digest((ROOT / "evaluation/acceptance.cjs").read_bytes()),
            "evaluation_module_sha256": _digest((ROOT / "backend/repopilot/evaluation.py").read_bytes()),
            "verifier_module_sha256": _digest((ROOT / "backend/repopilot/verifier.py").read_bytes()),
            "implementation_before_sha256": _digest(original),
        },
        "dependency_install": installed.model_dump(),
        "mutation": mutation,
        "rows": rows,
        "interpretation": {
            "green_proves": "The committed baseline plus the added test passed the configured regression command and file checks.",
            "green_does_not_prove": "The new test would catch the specific future regression required by the task.",
            "why_mutant_run_is_candidate_only": "Existing regression tests must not receive credit for the protection added by this candidate test.",
            "limitations": "One authored task and one known mutant; not an LLM success rate, adversarial sandbox, complete correctness proof or held-out generalization study. Candidate TypeScript executes in a host process. Run trusted code only.",
        },
        "redaction": "Exact workspace and local source-checkout paths replaced with placeholders in recorded output; exit codes, measured timings and assertion messages retained.",
    }
    serialized = json.dumps(report, indent=2)
    for location, label in [(str(workspace), "<workspace>"), (str(repository), "<source-checkout>")]:
        serialized = serialized.replace(json.dumps(location)[1:-1], label)
        serialized = serialized.replace(location.replace("\\", "/"), label)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized, encoding="utf-8")
    return json.loads(serialized)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("--trust-code", action="store_true", help="Allow executing this pinned repository's tests on this host")
    parser.add_argument("--data", type=Path, default=ROOT / ".repopilot/decision-case")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/decision-case.json")
    args = parser.parse_args()
    if not args.trust_code:
        parser.error("Pass --trust-code only for repository code you trust; this is not an OS sandbox")
    report = asyncio.run(run_case(args.repository, args.data, args.output))
    print(json.dumps({"case_proven": report["case_proven"], "output": str(args.output)}))
    if not report["case_proven"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
