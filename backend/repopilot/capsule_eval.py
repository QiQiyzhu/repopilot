"""Frozen public-development context comparison; real API calls require --execute.

Run controls first. No hidden oracle is supplied to the actor or mounted into a
candidate container. Public authored tasks are NOT held-out generalization data.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import time
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from .capsule_sandbox import VISIBLE_COMMAND, CapsuleRouter, DockerSandbox
from .config import PROJECT_ROOT
from .context import token_estimate
from .harness import Harness
from .interfaces import ModelProvider
from .models import Acceptance, Budget, Check, ModelReply, TaskRequest, now
from .provider_check import source_receipt
from .providers import OpenAIProvider, ProviderError
from .security import redact_data, run_process

PACK = PROJECT_ROOT / "evaluation/capsules/v1"
PROFILES: dict[str, tuple[Literal["naive", "structured"], int]] = {
    "full": ("naive", 6000), "compact": ("structured", 900)
}
LIMITS = {
    "calls_per_trial": 6, "total_calls": 72, "output_tokens_per_call": 1536,
    "observed_tokens_per_trial": 20000, "observed_tokens_total": 250000,
    "trial_seconds": 90, "batch_seconds": 1200, "provider_retries": 0,
}


def digest(value: Any) -> str:
    # Mapping declaration order is part of the dependency-order task contract.
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_pack(directory: Path = PACK) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    lock = json.loads((directory / "freeze.json").read_text(encoding="utf-8"))
    for name in ["tasks.json", "oracle.json"]:
        data = json.loads((directory / name).read_text(encoding="utf-8"))
        if digest(data) != lock["content_sha256"][name]:
            raise ValueError(f"Frozen pack drift: {name}")
    tasks = json.loads((directory / "tasks.json").read_text(encoding="utf-8"))
    oracle = json.loads((directory / "oracle.json").read_text(encoding="utf-8"))
    if lock["limits"] != LIMITS or lock["profiles"] != {k: list(v) for k, v in PROFILES.items()}:
        raise ValueError("Frozen protocol drift")
    if len(tasks["tasks"]) != 6 or {t["id"] for t in tasks["tasks"]} != set(oracle["tasks"]):
        raise ValueError("Frozen task inventory mismatch")
    return tasks, oracle, lock


def visible_tests(task: dict[str, Any]) -> str:
    return (
        "import json, unittest\nfrom solution import solve\n\nclass VisibleTests(unittest.TestCase):\n"
        + "".join(
            f"    def test_example_{index}(self):\n"
            f"        value, expected = json.loads({json.dumps(pair)!r})\n"
            "        original = json.dumps(value, sort_keys=True)\n"
            "        self.assertEqual(solve(value), expected)\n"
            "        self.assertEqual(json.dumps(value, sort_keys=True), original)\n"
            for index, pair in enumerate(task["visible"])
        )
    )


async def materialize(task: dict[str, Any], root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=False)
    files = {
        "solution.py": task["initial"], "test_visible.py": visible_tests(task),
        "README.md": "# Authored public development capsule\n" + task["instruction"] + "\n",
    }
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    for command in [
        ["git", "init", "--quiet"], ["git", "add", "."],
        ["git", "-c", "user.name=RepoPilot", "-c", "user.email=repopilot@localhost",
         "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Frozen public development fixture"],
    ]:
        result = await run_process(command, root)
        if not result.ok:
            raise RuntimeError("capsule_repository_setup_failed")
    return root


def json_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(expected, (int, float)):
        return isinstance(actual, (int, float)) and actual == expected
    if type(expected) is list:
        return type(actual) is list and len(actual) == len(expected) and all(
            json_equal(a, b) for a, b in zip(actual, expected, strict=True)
        )
    if type(expected) is dict:
        return type(actual) is dict and actual.keys() == expected.keys() and all(
            json_equal(actual[key], value) for key, value in expected.items()
        )
    return type(actual) is type(expected) and actual == expected


def classify(result: Any, expected: list[Any]) -> dict[str, Any]:
    """Strict controller-owned grading; nonzero exits never count as successful kills."""
    if not result.ok or result.exit_code != 0 or result.truncated:
        return {"passed": False, "classification": "execution_inconclusive", "case_passes": 0,
                "case_count": len(expected), "error": result.error, "exit_code": result.exit_code}
    try:
        observed = json.loads(result.output)
        if not isinstance(observed, list) or len(observed) != len(expected):
            raise ValueError
        matches = [
            type(row) is dict and set(row) == {"value", "input_unchanged"}
            and row["input_unchanged"] is True
            # JSON type equality matters: true is not an integer 1.
            and json_equal(row["value"], want)
            for row, want in zip(observed, expected, strict=True)
        ]
    except (ValueError, TypeError):
        return {"passed": False, "classification": "protocol_invalid", "case_passes": 0,
                "case_count": len(expected), "exit_code": 0}
    return {"passed": all(matches), "classification": "accepted" if all(matches) else "contract_rejected",
            "case_passes": sum(matches), "case_count": len(expected), "case_results": matches,
            "observed": observed, "exit_code": 0}


async def grade(sandbox: DockerSandbox, code: str, cases: list[list[Any]]) -> dict[str, Any]:
    result = await sandbox.execute(code, inputs=[pair[0] for pair in cases])
    return {**classify(result, [pair[1] for pair in cases]), "duration_ms": result.duration_ms}


class CallLedger:
    """Durable reservation before HTTP; no auto-resume or unknown-usage retry."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("x", encoding="utf-8")
        self.calls = 0
        self.observed_tokens = 0
        self.unknown_usage = False
        self.started = time.monotonic()

    def append(self, event: dict[str, Any]) -> None:
        self.file.write(json.dumps({"at": now(), **event}, ensure_ascii=False) + "\n")
        self.file.flush()
        os.fsync(self.file.fileno())

    def reserve(self, trial: str, messages: list[dict[str, Any]], output: int) -> str:
        if self.unknown_usage:
            raise ProviderError("batch_stopped_unknown_billed_usage")
        if self.calls >= LIMITS["total_calls"]:
            raise ProviderError("batch_call_budget_exhausted")
        if time.monotonic() - self.started >= LIMITS["batch_seconds"]:
            raise ProviderError("batch_wall_budget_exhausted")
        estimated = token_estimate(json.dumps(messages))
        if self.observed_tokens + estimated + output > LIMITS["observed_tokens_total"]:
            raise ProviderError("batch_token_budget_exhausted")
        call = str(uuid4())
        self.calls += 1
        self.append({"event": "reserved", "call_id": call, "trial": trial,
                     "request_sha256": digest(messages), "estimated_input_tokens": estimated,
                     "max_output_tokens": output, "usage": None})
        return call


class LedgerProvider:
    name = "capsule-bounded-provider"

    def __init__(self, provider: ModelProvider, ledger: CallLedger, trial: str):
        self.provider, self.ledger, self.trial = provider, ledger, trial
        self.calls = 0

    async def complete(self, messages: list[dict[str, Any]], max_tokens: int) -> ModelReply:
        if self.calls >= LIMITS["calls_per_trial"]:
            raise ProviderError("trial_call_budget_exhausted")
        output = min(max_tokens, LIMITS["output_tokens_per_call"])
        call = self.ledger.reserve(self.trial, messages, output)
        self.calls += 1
        started = time.monotonic()
        try:
            reply = await self.provider.complete(messages, output)
        except BaseException as error:
            self.ledger.unknown_usage = True
            self.ledger.append({"event": "outcome_unknown", "call_id": call, "trial": self.trial,
                                "error_class": type(error).__name__, "usage": None})
            raise
        self.ledger.observed_tokens += reply.usage.input_tokens + reply.usage.output_tokens
        self.ledger.append({"event": "observed", "call_id": call, "trial": self.trial,
                            "usage": reply.usage.model_dump(), "provider": reply.provider_metadata,
                            "duration_ms": round((time.monotonic() - started) * 1000, 3)})
        if self.ledger.observed_tokens > LIMITS["observed_tokens_total"]:
            raise ProviderError("batch_observed_token_budget_exceeded")
        return reply


async def run_trial(
    task: dict[str, Any], profile: str, root: Path, sandbox: DockerSandbox,
    ledger: CallLedger, provider: ModelProvider,
) -> dict[str, Any]:
    trial = task["id"] + "--" + profile
    folder = root / trial
    repository = await materialize(task, folder / "repository")
    harness = Harness(folder / "harness", folder, PACK.parent / "skills",
                      router_factory=lambda path, allowed: CapsuleRouter(path, allowed, sandbox))
    strategy, context_tokens = PROFILES[profile]
    counted = LedgerProvider(provider, ledger, trial)
    request = TaskRequest(
        repository=str(repository), provider="openai", skill="capsule-repair",
        task=task["instruction"] + " Only modify solution.py. Reproduce using run_tests with exactly "
        + json.dumps(VISIBLE_COMMAND) + ". Use at most six actions: reproduce, patch, test, finish. "
        "Independent evaluation follows your final result; no hidden feedback is available.",
        context_strategy=strategy, memory_enabled=False, allow_repository_code=False,
        budget=Budget(max_steps=6, max_tokens=LIMITS["observed_tokens_per_trial"],
                      context_tokens=context_tokens, timeout_seconds=LIMITS["trial_seconds"],
                      max_repairs=0, provider_retries=0),
        acceptance=Acceptance(expected_files=["solution.py"], checks=[
            Check(name="frozen-visible-examples", command=VISIBLE_COMMAND, layer="unit")]),
    )
    actor = await harness.submit(request, counted)
    await harness.jobs[actor.task_id]
    result = harness.store.get_task(actor.task_id)
    assert result is not None
    workspace = Path(result.workspace) if result.workspace else None
    unchanged = workspace is not None and all(
        (workspace / name).read_bytes() == (repository / name).read_bytes()
        for name in ["README.md", "test_visible.py"]
    )
    candidate = (workspace / "solution.py").read_text(encoding="utf-8") if workspace else None
    row = {
        "trial_id": trial, "task_id": task["id"], "profile": profile,
        "actor_status": result.status, "actor_error": result.error,
        "provider_calls": counted.calls, "usage": result.usage.model_dump(),
        "latency_ms": result.latency_ms, "original_files_preserved": unchanged,
        "candidate": candidate, "candidate_sha256_lf": hashlib.sha256(candidate.encode()).hexdigest() if candidate else None,
        "task": result.model_dump(mode="json"),
    }
    write_json(folder / "actor.json", redact_data(row))
    return row


async def controls(sandbox: DockerSandbox, tasks: dict[str, Any], oracle: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for task in tasks["tasks"]:
        grading = oracle["tasks"][task["id"]]
        reference = await grade(sandbox, grading["reference"], grading["cases"])
        broken = await grade(sandbox, task["initial"], grading["cases"])
        visible = await sandbox.execute(grading["reference"], visible_tests=visible_tests(task))
        rows.append({"task_id": task["id"], "reference": reference, "broken": broken,
                     "reference_visible_passed": visible.ok and visible.exit_code == 0})
    probe = """def solve(p):
    import os, socket
    from pathlib import Path
    writable = True
    try:
        Path('/work/solution.py').write_text('changed')
    except OSError:
        writable = False
    network = True
    try:
        socket.create_connection(('1.1.1.1', 443), timeout=0.2).close()
    except OSError:
        network = False
    return {'uid': os.getuid(), 'writable': writable, 'network': network,
            'key_present': any('API_KEY' in k for k in os.environ),
            'files': sorted(x.name for x in Path('/work').iterdir())}
"""
    boundary = await grade(sandbox, probe, [[None, {
        "uid": 65534, "writable": False, "network": False, "key_present": False,
        "files": ["gateway.py", "solution.py", "test_visible.py"],
    }]])
    timeout = await grade(sandbox, "def solve(p):\n    while True: pass\n", [[None, 1]])
    malformed = await grade(sandbox, "print('not-json')\ndef solve(p):\n    return 1\n", [[None, 1]])
    all_passed = all(row["reference"]["passed"] and row["reference_visible_passed"]
                     and row["broken"]["classification"] == "contract_rejected" for row in rows)
    return {
        "status": "passed" if all_passed and boundary["passed"]
        and timeout["classification"] == "execution_inconclusive"
        and timeout.get("error") == "sandbox_timeout" and malformed["classification"] == "protocol_invalid" else "failed",
        "rows": rows, "boundary_probe": boundary, "timeout_probe": timeout,
        "malformed_probe": malformed, "model_calls": 0,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = {}
    for profile in PROFILES:
        selected = [row for row in rows if row["profile"] == profile]
        summaries[profile] = {
            "trials": len(selected), "passed": sum(row.get("passed", False) for row in selected),
            "provider_calls": sum(row.get("provider_calls", 0) for row in selected),
            "observed_input_tokens": sum(row.get("usage", {}).get("input_tokens", 0) for row in selected),
            "observed_output_tokens": sum(row.get("usage", {}).get("output_tokens", 0) for row in selected),
        }
    return summaries


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    tasks, oracle, lock = load_pack()
    source = source_receipt()
    source["capsule_source_sha256_lf"] = {
        name: hashlib.sha256((PROJECT_ROOT / name).read_text(encoding="utf-8").encode()).hexdigest()
        for name in ["backend/repopilot/capsule_eval.py", "backend/repopilot/capsule_sandbox.py",
                     "backend/repopilot/harness.py", "backend/repopilot/context.py",
                     "backend/repopilot/tools.py", "evaluation/capsules/skills/capsule-repair.md"]
    }
    report: dict[str, Any] = {
        "schema_version": 1, "recorded_at": now(), "source": source, "freeze": lock,
        "scope": tasks["evidence_scope"], "is_held_out": False,
        "limits": LIMITS, "configuration": None, "provider_calls": 0,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "limitation": "Six public authored tasks, one stochastic run per condition. Runtime withholding does not establish data novelty. No generalization, statistical significance, or leaderboard claim. Token limits stop on observations/estimates, not a prepaid lock; interrupted calls have unknown billed usage.",
    }
    if not args.execute and not args.controls:
        return {**report, "status": "dry_run", "planned_trials": 12, "network_checked": False}
    if args.execute and (source["git_commit"] != args.expected_commit or source["working_tree_dirty"]):
        return {**report, "status": "source_rejected", "error": "Execution requires the reviewed clean --expected-commit"}
    if not args.image:
        return {**report, "status": "not_configured", "error": "An immutable --image is required; no host fallback"}
    root = args.data.resolve()
    root.mkdir(parents=True, exist_ok=False)
    sandbox = DockerSandbox(args.image, root / "sandbox")
    report["environment"]["container"] = await sandbox.preflight()
    if args.controls:
        return {**report, **await controls(sandbox, tasks, oracle)}
    provider = OpenAIProvider()  # Explicit --execute only, controller env only.
    report["configuration"] = provider.config.public_status()
    report["status"] = "running"
    report["rows"] = []
    ledger = CallLedger(root / "calls.jsonl")
    try:
        # Counterbalance execution order; no fresh process inherits prior trial memory.
        for index, task in enumerate(tasks["tasks"]):
            for profile in (["full", "compact"] if index % 2 == 0 else ["compact", "full"]):
                try:
                    remaining = LIMITS["batch_seconds"] - (time.monotonic() - ledger.started)
                    if remaining <= 0 or ledger.unknown_usage:
                        raise ProviderError("batch_stopped_wall_or_unknown_usage")
                    async with asyncio.timeout(remaining):
                        row = await run_trial(task, profile, root, sandbox, ledger, provider)
                        if row["candidate"] is not None:
                            row["independent_verdict"] = await grade(
                                sandbox, row["candidate"], oracle["tasks"][task["id"]]["cases"])
                        row["passed"] = bool(row["actor_status"] == "succeeded"
                                              and row["original_files_preserved"]
                                              and row.get("independent_verdict", {}).get("passed"))
                except (ProviderError, TimeoutError) as error:
                    row = {"trial_id": task["id"] + "--" + profile, "task_id": task["id"],
                           "profile": profile, "passed": False, "status": "not_completed",
                           "error": type(error).__name__ + ": " + str(error)}
                report["rows"].append(row)
                report["provider_calls"] = ledger.calls
                report["observed_tokens"] = ledger.observed_tokens
                report["unknown_billed_usage"] = ledger.unknown_usage
                report["summary"] = summarize(report["rows"])
                write_json(args.output, redact_data(report))
        report["status"] = "completed"  # Completion includes failed trials; not a success verdict.
    finally:
        ledger.file.close()
    report["elapsed_seconds"] = round(time.monotonic() - ledger.started, 3)
    report["container_calls"] = sandbox.calls
    return redact_data(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--controls", action="store_true")
    parser.add_argument("--image")
    parser.add_argument("--expected-commit")
    parser.add_argument("--data", type=Path, required=True, help="New output directory; reruns cannot overwrite")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = asyncio.run(main_async(args))
    except (ValueError, OSError, RuntimeError) as error:
        report = {"status": "infrastructure_error", "error": type(error).__name__ + ": " + str(error)}
    write_json(args.output, report)
    print(json.dumps({k: v for k, v in report.items() if k in {"status", "provider_calls", "summary", "error"}}))
    raise SystemExit(0 if report["status"] in {"dry_run", "passed", "completed"} else 1)


if __name__ == "__main__":
    main()
