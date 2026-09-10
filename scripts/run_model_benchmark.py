"""Opt-in real-provider benchmark. Never executed by CI or the default demo.

Reference patches are not passed to the provider; external acceptance contracts grade each result.
"""

import argparse
import asyncio
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from repopilot.evaluation import PROFILES, ROOT, acceptance, apply_reference, contract_rejected
from repopilot.harness import Harness
from repopilot.models import Acceptance, Budget, Check, TaskRequest
from repopilot.providers import ProviderError, RemoteConfig
from repopilot.security import run_process, validate_command
from repopilot.workspace import GitWorkspace


def npm_command(arguments):
    if os.name == "nt":
        executable = shutil.which("npm.cmd")
        if not executable:
            raise RuntimeError("npm unavailable")
        return [
            shutil.which("node"),
            str(Path(executable).parent / "node_modules/npm/bin/npm-cli.js"),
            *arguments,
        ]
    return ["npm", *arguments]


async def main(args):
    if not args.confirm_paid_api:
        raise SystemExit(
            "Explicitly pass --confirm-paid-api. No fallback provider will run."
        )
    try:
        remote_config = RemoteConfig.from_environment()
    except ProviderError as error:
        raise SystemExit(str(error)) from None
    manifest = json.loads((ROOT / "evaluation/tasks/arc-shift.json").read_text())
    selected = [t for t in manifest["tasks"] if not args.task_id or t["task_id"] in args.task_id]
    if not selected:
        raise SystemExit("No matching benchmark task")
    args.data.mkdir(parents=True, exist_ok=True)
    rows = []
    factory = GitWorkspace(args.data / "sources", args.repository.resolve().parent)
    profiles = [p for p in PROFILES if not args.profile or p["id"] in args.profile]

    async def initialize(workspace):
        # Dependency installation is a trusted operator setup step, not an agent tool.
        setup = await run_process(
            npm_command(["ci", "--ignore-scripts", "--no-audit", "--no-fund"]),
            workspace,
            timeout=300,
        )
        if not setup.ok:
            raise RuntimeError("dependency_setup_failed: " + setup.output[-2000:])

    for task in selected:
        prepared, _ = await factory.create(
            str(args.repository.resolve()), manifest["repository_commit"], str(uuid4())
        )
        prepared = Path(prepared)
        if task["setup_patch"]:
            apply_reference(prepared, task["setup_patch"])
            await run_process(["git", "add", "."], prepared)
            committed = await run_process(
                [
                    "git",
                    "-c",
                    "user.name=RepoPilot",
                    "-c",
                    "user.email=repopilot@localhost",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-m",
                    "Benchmark negative control",
                ],
                prepared,
            )
            if not committed.ok:
                raise RuntimeError(committed.output)
        for profile in profiles:
            runner_data = args.data / "runs" / profile["id"]
            harness = Harness(
                runner_data, args.data, ROOT / "skills", workspace_initializer=initialize
            )
            config = {k: v for k, v in profile.items() if k not in {"id", "label"}}
            if profile["id"] == "single-shot":
                config.update(use_context=True, context_strategy="naive")
            if profile["id"] == "full":
                config["skill"] = {
                    "Add Test": "add-unit-test",
                    "Performance": "performance-investigation",
                }.get(task["category"], "bug-fix")
            request = TaskRequest(
                repository=str(prepared),
                task=task["description"],
                provider="openai",
                allow_repository_code=True,
                budget=Budget(timeout_seconds=1200, max_steps=30, max_tokens=args.max_tokens),
                acceptance=Acceptance(
                    checks=[
                        Check(name="regression", command=["npm", "run", "test"], layer="unit"),
                        Check(
                            name="typecheck", command=["npm", "run", "typecheck"], layer="syntax"
                        ),
                        Check(name="build", command=["npm", "run", "build"], layer="repository"),
                    ],
                    expected_files=task["required_files"],
                ),
                **config,
            )
            handle = await harness.submit(request)
            await harness.jobs[handle.task_id]
            result = harness.store.get_task(handle.task_id)
            external = None
            regression = []
            if result.workspace:
                workspace = Path(result.workspace)
                external = await acceptance(workspace, task, args.data)
                if task.get("adequacy_mutation") and external["passed"]:
                    mutation = task["adequacy_mutation"]
                    path = workspace / mutation["path"]
                    original = path.read_bytes()
                    try:
                        apply_reference(workspace, mutation)
                        killed = await acceptance(workspace, task, args.data)
                        external["mutation_killed"] = contract_rejected(killed)
                        external["passed"] &= external["mutation_killed"]
                    finally:
                        path.write_bytes(original)
                for check in request.acceptance.checks:
                    verified = await run_process(
                        validate_command(check.command, workspace, True), workspace, timeout=120
                    )
                    regression.append({"name": check.name, **verified.model_dump()})
            tools = [e for e in result.trace if e.kind == "tool"]
            rows.append(
                {
                    "task_id": task["task_id"],
                    "run_id": result.task_id,
                    "profile": profile["id"],
                    "provider": "openai",
                    "model": remote_config.model,
                    "provider_flavor": remote_config.flavor,
                    "passed": bool(
                        external
                        and external["passed"]
                        and regression
                        and all(c["ok"] for c in regression)
                    ),
                    "acceptance": external,
                    "checks": regression,
                    "steps": result.step_count,
                    "latency_ms": result.latency_ms,
                    "usage": result.usage.model_dump(),
                    "repair_attempts": result.repair_count,
                    "tool_errors": sum(not e.result.ok for e in tools if e.result),
                    "status": result.status,
                    "error": result.error,
                }
            )
            report = {
                "id": "real-model-ablation",
                "is_model_benchmark": True,
                "repository_commit": manifest["repository_commit"],
                "selected_tasks": len(selected),
                "profiles": [p["id"] for p in profiles],
                "completed_runs": len(rows),
                "rows": rows,
                "note": "Single-shot receives a bounded naive snapshot; other ablations progressively enable tools, verification, structured retrieval, memory/skills. No reference patch is sent to a model. First memory runs are cold; interpret that limitation.",
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(
                json.dumps({k: rows[-1][k] for k in ["task_id", "profile", "passed", "steps"]}),
                flush=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    parser.add_argument("--confirm-paid-api", action="store_true")
    parser.add_argument("--task-id", action="append")
    parser.add_argument("--profile", action="append", choices=[p["id"] for p in PROFILES])
    parser.add_argument("--max-tokens", type=int, default=100000)
    parser.add_argument("--data", type=Path, default=ROOT / ".repopilot/real-evaluation")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "evaluation/results/real-model-ablation.json"
    )
    asyncio.run(main(parser.parse_args()))
