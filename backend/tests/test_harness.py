import asyncio
from pathlib import Path

from repopilot.models import Action, Budget, ModelReply, State, TaskRequest
from repopilot.providers import FakeModelProvider, ProviderError


async def complete(harness, repo, **kwargs):
    request = TaskRequest(
        repository=str(repo), task="Fix clamp boundary bug", allow_repository_code=True, **kwargs
    )
    task = await harness.submit(request)
    await harness.jobs[task.task_id]
    return harness.store.get_task(task.task_id)


async def test_native_end_to_end_with_real_tests_and_isolation(harness, repo):
    original = (repo / "calculator.py").read_text()
    task = await complete(harness, repo)
    assert task.status == "succeeded"
    assert task.step_count == 7 and task.test_result["passed"]
    assert "min(high, value)" in task.final_diff
    assert (repo / "calculator.py").read_text() == original
    assert "max(high, value)" in original
    assert task.repository_commit and task.workspace != str(repo)
    assert all(e.transport == "native" for e in task.trace if e.kind == "tool")
    assert any(e.result.exit_code == 1 for e in task.trace if e.tool == "run_tests")
    assert any(e.result.exit_code == 0 for e in task.trace if e.tool == "run_tests")
    assert len(harness.store.all_memory()) == 2
    assert task.evidence_label == "harness-demonstration"


async def test_mcp_end_to_end_uses_real_stdio_transport(harness, repo):
    task = await complete(harness, repo, transport="mcp")
    assert task.status == "succeeded", task.error
    assert {e.tool for e in task.trace if e.transport == "mcp"} >= {
        "read_file",
        "run_tests",
        "git_diff",
    }
    assert any(e.transport == "native" and e.tool == "apply_patch" for e in task.trace)


async def test_replay_provider_reexecutes_real_tools(harness, repo):
    original = await complete(harness, repo)
    replay = await complete(harness, repo, provider="replay", replay_id=original.task_id)
    assert replay.status == "succeeded"
    assert replay.evidence_label == "replay-validation"
    assert replay.workspace != original.workspace


async def test_skill_prevents_patch_before_reproduction(harness, repo):
    provider = FakeModelProvider(
        [
            Action(
                kind="tool",
                summary="Attempt early patch",
                tool="apply_patch",
                arguments={
                    "path": "calculator.py",
                    "old": "max(high, value)",
                    "new": "min(high, value)",
                },
            ),
            Action(kind="finish", summary="Try finish"),
        ]
    )
    task = await harness.submit(
        TaskRequest(
            repository=str(repo),
            task="Fix clamp",
            allow_repository_code=True,
            budget=Budget(max_repairs=0),
        ),
        provider,
    )
    await harness.jobs[task.task_id]
    result = harness.store.get_task(task.task_id)
    assert result.status == "failed"
    assert any(e.result and "reproduction" in (e.result.error or "") for e in result.trace)


async def test_repair_is_bounded_after_verifier_rejects(harness, repo):
    provider = FakeModelProvider([Action(kind="finish", summary="Unsupported completion")])
    task = await harness.submit(
        TaskRequest(
            repository=str(repo),
            task="Fix bug",
            allow_repository_code=True,
            budget=Budget(max_repairs=1),
        ),
        provider,
    )
    await harness.jobs[task.task_id]
    result = harness.store.get_task(task.task_id)
    assert result.status == "failed" and result.repair_count == 1
    assert State.REPAIR in [e.state for e in result.trace]
    assert not harness.store.all_memory()


async def test_max_steps(harness, repo):
    result = await complete(harness, repo, budget=Budget(max_steps=1))
    assert result.status == "failed" and "max_steps" in result.error


async def test_context_overflow(harness, repo):
    result = await complete(harness, repo, budget=Budget(max_tokens=64))
    assert result.status == "failed" and "context_overflow" in result.error


class SlowProvider:
    name = "slow"

    async def complete(self, messages, max_tokens):
        await asyncio.sleep(10)
        return ModelReply(action=Action(kind="finish", summary="Too late"))


async def test_task_timeout(harness, repo):
    task = await harness.submit(
        TaskRequest(repository=str(repo), task="Fix bug", budget=Budget(timeout_seconds=0.15)),
        SlowProvider(),
    )
    await harness.jobs[task.task_id]
    assert harness.store.get_task(task.task_id).status == "timed_out"


async def test_cancel_active_task(harness, repo):
    task = await harness.submit(TaskRequest(repository=str(repo), task="Fix bug"), SlowProvider())
    await asyncio.sleep(0.2)
    assert await harness.cancel(task.task_id)
    assert harness.store.get_task(task.task_id).status == "cancelled"


class FailThenSucceed:
    name = "flaky"

    def __init__(self):
        self.calls = 0
        self.fake = FakeModelProvider()

    async def complete(self, messages, max_tokens):
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("transient outage", retryable=True)
        return await self.fake.complete(messages, max_tokens)


async def test_provider_retries_without_fake_fallback(harness, repo):
    provider = FailThenSucceed()
    task = await harness.submit(
        TaskRequest(repository=str(repo), task="Fix clamp", allow_repository_code=True), provider
    )
    await harness.jobs[task.task_id]
    result = harness.store.get_task(task.task_id)
    assert result.status == "succeeded" and provider.calls == 8
    assert any(e.kind == "provider-error" for e in result.trace)


async def test_permanent_provider_failure_is_not_retried(harness, repo):
    class RejectedProvider:
        name = "rejected"
        calls = 0

        async def complete(self, messages, max_tokens):
            self.calls += 1
            raise ProviderError("provider_http_401")

    provider = RejectedProvider()
    task = await harness.submit(TaskRequest(repository=str(repo), task="Fix clamp"), provider)
    await harness.jobs[task.task_id]
    result = harness.store.get_task(task.task_id)
    assert provider.calls == 1 and result.status == "failed" and result.step_count == 0


async def test_missing_real_key_fails_explicitly(harness, repo, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = await complete(harness, repo, provider="openai")
    assert result.status == "failed" and "OPENAI_API_KEY" in result.error
    assert result.evidence_label == "real-provider-run"
    assert result.step_count == 0


async def test_no_verifier_does_not_claim_success(harness, repo):
    result = await complete(harness, repo, use_verifier=False)
    assert result.status == "unverified" and result.test_result is None


async def test_memory_disabled_writes_nothing(harness, repo):
    result = await complete(harness, repo, memory_enabled=False)
    assert result.status == "succeeded" and not harness.store.all_memory()


async def test_untracked_new_file_is_in_diff(harness, repo):
    from repopilot.tools import ToolRouter

    task = await complete(harness, repo)
    router = ToolRouter(Path(task.workspace))
    await router.invoke("apply_patch", {"path": "new.py", "new": "answer = 42\n"})
    assert "b/new.py" in (await router.invoke("git_diff", {})).output


async def test_approval_gate_waits_for_explicit_decision(harness, repo):
    provider = FakeModelProvider(
        [
            Action(
                kind="tool",
                summary="Delete README",
                tool="apply_patch",
                arguments={"path": "README.md", "delete": True},
            ),
            Action(kind="finish", summary="done"),
        ]
    )
    task = await harness.submit(
        TaskRequest(repository=str(repo), task="Remove README", skill=None, use_verifier=False),
        provider,
    )
    for _ in range(100):
        if harness.store.get_task(task.task_id).status == "awaiting_approval":
            break
        await asyncio.sleep(0.02)
    current = harness.store.get_task(task.task_id)
    assert current.status == "awaiting_approval"
    assert (Path(current.workspace) / "README.md").exists()
    assert harness.approve(task.task_id, False)
    await harness.jobs[task.task_id]
    result = harness.store.get_task(task.task_id)
    assert result.status == "failed"
    assert (Path(result.workspace) / "README.md").exists()


async def test_workspace_retains_gitignore_but_excludes_env(harness, repo):
    from repopilot.security import run_process

    (repo / ".gitignore").write_text("node_modules/\n")
    (repo / ".env").write_text("SECRET=private-value\n")
    await run_process(["git", "add", ".gitignore", ".env"], repo)
    committed = await run_process(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@localhost",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "Protected fixture files",
        ],
        repo,
    )
    assert committed.ok
    result = await complete(harness, repo)
    assert (Path(result.workspace) / ".gitignore").read_text() == "node_modules/\n"
    assert not (Path(result.workspace) / ".env").exists()
