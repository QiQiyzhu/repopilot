import pytest
from repopilot.models import Action
from repopilot.provider_task import BoundedProvider, run_fixture
from repopilot.providers import FakeModelProvider, ProviderError


async def test_fixture_opt_in_precedes_network_or_workspace_creation(tmp_path):
    data = tmp_path / "not-created"
    report = await run_fixture(execute=False, data=data)
    assert report["provider_calls_attempted"] == 0 and not data.exists()


async def test_fixture_call_bound_counts_failed_attempts_and_caps_output():
    class FailingProvider:
        name = "failure"
        budgets = []

        async def complete(self, messages, max_tokens):
            self.budgets.append(max_tokens)
            raise ProviderError("provider_http_429", retryable=True)

    delegate = FailingProvider()
    bounded = BoundedProvider(delegate)
    for _ in range(7):
        with pytest.raises(ProviderError):
            await bounded.complete([], 10000)
    assert bounded.calls == len(delegate.budgets) == 6
    assert delegate.budgets == [4000] * 6


async def test_fixture_reports_actual_acceptance_but_labels_injected_provider(tmp_path):
    provider = FakeModelProvider(
        actions=[
            Action(
                kind="tool",
                summary="Reproduce",
                tool="run_tests",
                arguments={"command": ["python", "-m", "pytest", "-q"]},
            ),
            Action(
                kind="tool",
                summary="Repair",
                tool="apply_patch",
                arguments={
                    "path": "calculator.py",
                    "old": "return max(low, max(high, value))",
                    "new": "return max(low, min(high, value))",
                },
            ),
            Action(kind="finish", summary="Submit for independent checks"),
        ]
    )
    report = await run_fixture(execute=True, data=tmp_path, provider=provider)
    assert report["status"] == "passed" and all(report["checks"].values())
    assert report["provider_calls_attempted"] == 3 and report["real_model_runs"] == 0
    assert report["evidence_type"] == "injected-provider-fixture-control"
    assert report["task"]["test_result"]["passed"]
