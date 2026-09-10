from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import PROJECT_ROOT
from .demo import create_demo_repository
from .harness import Harness
from .models import Action, TaskRequest
from .providers import FakeModelProvider
from .security import resolve_inside, run_process
from .workspace import GitWorkspace

ROOT = PROJECT_ROOT
PROFILES: list[dict[str, Any]] = [
    {
        "id": "single-shot",
        "label": "Single-shot patch",
        "single_shot": True,
        "use_verifier": False,
        "use_context": False,
        "memory_enabled": False,
        "skill": None,
    },
    {
        "id": "tools",
        "label": "Agent + tools",
        "single_shot": False,
        "use_verifier": False,
        "use_context": False,
        "memory_enabled": False,
        "skill": None,
    },
    {
        "id": "verifier",
        "label": "Agent + tools + verifier",
        "single_shot": False,
        "use_verifier": True,
        "use_context": False,
        "memory_enabled": False,
        "skill": None,
    },
    {
        "id": "context",
        "label": "+ structured context",
        "single_shot": False,
        "use_verifier": True,
        "use_context": True,
        "memory_enabled": False,
        "skill": None,
    },
    {
        "id": "full",
        "label": "+ memory + skills",
        "single_shot": False,
        "use_verifier": True,
        "use_context": True,
        "memory_enabled": True,
        "skill": "bug-fix",
    },
]


def apply_reference(root: Path, patch: dict[str, str]) -> None:
    """Trusted benchmark setup/reference control. Never supplied to ModelProvider."""
    path = resolve_inside(root, patch["path"])
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    before = patch.get("old", "")
    if before:
        if old.count(before) != 1:
            raise ValueError(
                f"Benchmark patch must match once: {patch['path']} ({old.count(before)} matches)"
            )
        new = old.replace(before, patch["new"], 1)
    else:
        if path.exists():
            raise ValueError(f"New-file control already exists: {path}")
        new = patch["new"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8", newline="")


async def acceptance(workspace: Path, task: dict[str, Any], data: Path) -> dict[str, Any]:
    descriptor = data / "current-task.json"
    descriptor.write_text(json.dumps(task), encoding="utf-8")
    result = await run_process(
        ["node", str(ROOT / "evaluation/acceptance.cjs"), str(workspace), str(descriptor)],
        ROOT,
        timeout=30,
    )
    return {
        "passed": result.ok,
        "exit_code": result.exit_code,
        "latency_ms": result.duration_ms,
        "output": result.output,
    }


async def validate_contracts(repository: Path, output: Path, data: Path) -> dict[str, Any]:
    manifest = json.loads((ROOT / "evaluation/tasks/arc-shift.json").read_text(encoding="utf-8"))
    data.mkdir(parents=True, exist_ok=True)
    factory = GitWorkspace(data / "workspaces", repository.parent)
    location, sha = await factory.create(
        str(repository), manifest["repository_commit"], str(uuid4())
    )
    workspace = Path(location)
    rows = []
    for task in manifest["tasks"]:
        patches = [
            p
            for p in [
                task.get("setup_patch"),
                task["reference_patch"],
                task.get("extra_reference_patch"),
                task.get("adequacy_mutation"),
            ]
            if p
        ]
        originals = {
            p["path"]: (workspace / p["path"]).read_bytes()
            if (workspace / p["path"]).exists()
            else None
            for p in patches
        }
        try:
            if task["setup_patch"]:
                apply_reference(workspace, task["setup_patch"])
            before = await acceptance(workspace, task, data)
            apply_reference(workspace, task["reference_patch"])
            if task.get("extra_reference_patch"):
                apply_reference(workspace, task["extra_reference_patch"])
            after = await acceptance(workspace, task, data)
            adequacy = None
            if task.get("adequacy_mutation"):
                apply_reference(workspace, task["adequacy_mutation"])
                adequacy = await acceptance(workspace, task, data)
            passed = (
                not before["passed"]
                and after["passed"]
                and (adequacy is None or not adequacy["passed"])
            )
            row = {
                "task_id": task["task_id"],
                "category": task["category"],
                "validated": passed,
                "negative_control": before,
                "reference_control": after,
                "mutation_adequacy": adequacy,
            }
            rows.append(row)
            print(json.dumps({"task_id": task["task_id"], "validated": passed}), flush=True)
        finally:
            for relative, original in originals.items():
                target = resolve_inside(workspace, relative)
                if original is None:
                    if target.exists():
                        target.unlink()
                else:
                    target.write_bytes(original)
    report = {
        "id": "arc-contract-validation",
        "title": "ARC//SHIFT task-contract validation",
        "evidence_type": "reference-and-negative-controls",
        "is_model_benchmark": False,
        "repository_commit": sha,
        "task_count": len(rows),
        "validated_count": sum(r["validated"] for r in rows),
        "real_model_runs": 0,
        "model_performance": None,
        "regression_status": "separate pinned-baseline regression report",
        "note": "Reference patches are an oracle control used to validate tasks. They are never a model provider, and these results do not measure an LLM's ability to solve tasks.",
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


async def ablate_fixture(output: Path, data: Path) -> dict[str, Any]:
    data.mkdir(parents=True, exist_ok=True)
    repository = await create_demo_repository(data / "fixture")
    harness = Harness(data / "runner", data, ROOT / "skills")
    warmup = await harness.submit(
        TaskRequest(
            repository=str(repository), task="Fix clamp boundary bug", allow_repository_code=True
        )
    )
    await harness.jobs[warmup.task_id]
    rows = []
    for profile in PROFILES:
        config = {k: v for k, v in profile.items() if k not in {"id", "label"}}
        provider = (
            FakeModelProvider(
                [
                    Action(
                        kind="tool",
                        summary="Scripted single-shot patch; known fixture only",
                        tool="apply_patch",
                        arguments={
                            "path": "calculator.py",
                            "old": "max(high, value)",
                            "new": "min(high, value)",
                        },
                    )
                ]
            )
            if config["single_shot"]
            else FakeModelProvider()
        )
        task = await harness.submit(
            TaskRequest(
                repository=str(repository),
                task="Fix clamp boundary bug",
                allow_repository_code=True,
                **config,
            ),
            provider,
        )
        await harness.jobs[task.task_id]
        result = harness.store.get_task(task.task_id)
        assert result and result.workspace
        from .security import validate_command

        workspace = Path(result.workspace)
        check = await run_process(
            validate_command(["python", "-m", "pytest", "-q"], workspace, True), workspace
        )
        tool_events = [e for e in result.trace if e.kind == "tool"]
        rows.append(
            {
                "profile": profile["id"],
                "label": profile["label"],
                "task_id": result.task_id,
                "provider": "deterministic-fake",
                "sample_count": 1,
                "independent_acceptance_passed": check.ok,
                "test_pass_rate": 1.0 if check.ok else 0.0,
                "status": result.status,
                "steps": result.step_count,
                "latency_ms": round(result.latency_ms, 2),
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": None,
                "tool_errors": sum(not e.result.ok for e in tool_events if e.result),
                "repair_attempts": result.repair_count,
                "context_tokens": result.context.get("context_tokens", 0),
                "memory_chunks": sum(
                    c["source"] == "trusted-memory"
                    for c in result.context.get("retrieved_chunks", [])
                ),
                "acceptance_exit_code": check.exit_code,
            }
        )
    report = {
        "id": "harness-ablation",
        "title": "Five configuration wiring checks on a known fixture",
        "evidence_type": "deterministic-harness-validation",
        "is_model_benchmark": False,
        "sample_count": 5,
        "real_model_runs": 0,
        "warmup_task_id": warmup.task_id,
        "rows": rows,
        "conclusion": "All configurations receive the same known scripted repair. Success equality is expected and shows neither model improvement nor generalization. Extra verifier/context/memory work adds overhead. Real 36-task model ablations remain not run.",
        "model_ablation": [
            {
                "profile": p["id"],
                "status": "not_run",
                "success_rate": None,
                "reason": "Requires an explicitly authorized, configured real provider",
            }
            for p in PROFILES
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run actual acceptance contracts; never fabricate LLM scores"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    contracts = sub.add_parser("validate-contracts")
    contracts.add_argument("repository", type=Path)
    contracts.add_argument(
        "--output", type=Path, default=ROOT / "evaluation/results/arc-contract-validation.json"
    )
    contracts.add_argument("--data", type=Path, default=ROOT / ".repopilot/benchmark")
    ablation = sub.add_parser("ablate-fixture")
    ablation.add_argument(
        "--output", type=Path, default=ROOT / "evaluation/results/harness-ablation.json"
    )
    ablation.add_argument("--data", type=Path, default=ROOT / ".repopilot/ablation")
    args = parser.parse_args()
    started = time.monotonic()
    if args.command == "validate-contracts":
        result = asyncio.run(validate_contracts(args.repository.resolve(), args.output, args.data))
        if result["validated_count"] != result["task_count"]:
            raise SystemExit(1)
    else:
        result = asyncio.run(ablate_fixture(args.output, args.data))
    print(f"Wrote {args.output}; elapsed {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
