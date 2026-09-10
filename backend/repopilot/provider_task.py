"""One real-provider execution on an authored, trusted clamp fixture.

This is a narrow end-to-end integration experiment, not a representative coding
benchmark. No reference patch is supplied to the remote provider.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import PROJECT_ROOT
from .demo import create_demo_repository
from .harness import Harness
from .interfaces import ModelProvider
from .models import Acceptance, Budget, Check, ModelReply, TaskRequest, now
from .provider_check import source_receipt, write_report
from .providers import OpenAIProvider, ProviderError
from .security import redact_data


class BoundedProvider:
    """Count attempted calls, including failures, independently of successful steps."""

    name = "bounded-fixture-provider"

    def __init__(self, provider: ModelProvider):
        self.provider = provider
        self.calls = 0

    async def complete(self, messages: list[dict[str, Any]], max_tokens: int) -> ModelReply:
        if self.calls >= 6:
            raise ProviderError("fixture_call_budget_exhausted")
        self.calls += 1
        return await self.provider.complete(messages, min(max_tokens, 4000))


async def run_fixture(
    *, execute: bool, data: Path, provider: ModelProvider | None = None
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "recorded_at": now(),
        "evidence_type": "real-provider-authored-fixture"
        if provider is None
        else "injected-provider-fixture-control",
        "is_model_benchmark": False,
        "provider_calls_attempted": 0,
        "real_model_runs": 0,
        "source": source_receipt(),
        "limits": {
            "max_provider_calls": 6,
            "retries": 0,
            "max_output_tokens_per_call": 4000,
            "max_total_observed_tokens": 16000,
            "max_steps": 6,
            "timeout_seconds": 180,
        },
        "limitation": "One authored clamp fixture, visible tests, trusted host code, no random sample or ablation. Acceptance checks executable behavior but not general coding ability. Token/cost stops are observed bounds, not a prepaid lock; interrupted API usage may be unknown.",
    }
    report["source"]["source_sha256_lf"].update(
        {
            name: hashlib.sha256(
                (Path(__file__).parent / name).read_text(encoding="utf-8").encode()
            ).hexdigest()
            for name in ["provider_task.py", "harness.py", "models.py", "demo.py", "verifier.py"]
        }
    )
    if not execute:
        return {**report, "status": "not_authorized", "error": "Explicit --execute required"}
    try:
        actual = provider or OpenAIProvider()
    except ProviderError as error:
        return {**report, "status": "not_configured", "error": str(error)}
    if isinstance(actual, OpenAIProvider):
        report["configuration"] = actual.config.public_status()
    attempt = data.resolve() / str(uuid4())
    repository = await create_demo_repository(attempt / "authored-fixture")
    report["fixture_sha256_lf"] = {
        name: hashlib.sha256((repository / name).read_text(encoding="utf-8").encode()).hexdigest()
        for name in ["calculator.py", "test_calculator.py", "README.md"]
    }
    counted = BoundedProvider(actual)
    harness = Harness(attempt / "harness", attempt, PROJECT_ROOT / "skills")
    request = TaskRequest(
        repository=str(repository),
        task="Repair the authored clamp fixture so values below the interval clamp to low, values inside are unchanged, and values above clamp to high. Preserve the tests. Use the supplied context, reproduce the failure before patching, and finish within six actions. Do not add unrelated files.",
        provider="openai",
        allow_repository_code=True,
        memory_enabled=False,
        budget=Budget(
            max_steps=6,
            max_tokens=16000,
            timeout_seconds=180,
            max_repairs=0,
            provider_retries=0,
            context_tokens=1800,
        ),
        acceptance=Acceptance(
            checks=[
                Check(
                    name="authored-clamp-tests",
                    command=["python", "-m", "pytest", "-q"],
                    layer="unit",
                )
            ],
            expected_files=["calculator.py"],
        ),
    )
    task = await harness.submit(request, counted)
    await harness.jobs[task.task_id]
    result = harness.store.get_task(task.task_id)
    assert result is not None
    workspace = Path(result.workspace) if result.workspace else None
    tests_unchanged = (
        workspace is not None
        and (workspace / "test_calculator.py").is_file()
        and (workspace / "test_calculator.py").read_bytes()
        == (repository / "test_calculator.py").read_bytes()
    )
    only_expected_file = result.test_result is not None and result.test_result["changed_files"] == [
        "calculator.py"
    ]
    report.update(
        status="passed"
        if result.status == "succeeded" and tests_unchanged and only_expected_file
        else "failed",
        provider_calls_attempted=counted.calls,
        real_model_runs=int(provider is None and counted.calls > 0),
        checks={
            "harness_acceptance": result.status == "succeeded",
            "original_tests_unchanged": tests_unchanged,
            "only_expected_file_changed": only_expected_file,
        },
        usage=result.usage.model_dump(),
        task=result.model_dump(mode="json"),
    )
    return redact_data(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--data", type=Path, default=PROJECT_ROOT / ".repopilot/provider-fixture")
    parser.add_argument("--output", type=str)
    args = parser.parse_args()
    report = asyncio.run(run_fixture(execute=args.execute, data=args.data))
    write_report(report, args.output)
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
