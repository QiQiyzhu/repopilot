import argparse
import asyncio
import json
from pathlib import Path

import pytest
from repopilot.capsule_eval import (
    LIMITS,
    CallLedger,
    LedgerProvider,
    classify,
    digest,
    json_equal,
    load_pack,
    main_async,
    materialize,
    run_trial,
)
from repopilot.capsule_sandbox import (
    VISIBLE_COMMAND,
    CapsuleRouter,
    DockerSandbox,
    SandboxUnavailable,
)
from repopilot.models import Action, ModelReply, ToolResult, Usage
from repopilot.providers import FakeModelProvider, ProviderError


def test_frozen_pack_inventory_and_drift_rejection(tmp_path):
    tasks, oracle, lock = load_pack()
    assert len(tasks['tasks']) == 6
    assert sum(len(t['cases']) for t in oracle['tasks'].values()) == 39
    assert lock['oracle_public_in_source'] is True
    for filename, value in [('tasks.json', tasks), ('oracle.json', oracle), ('freeze.json', lock)]:
        (tmp_path / filename).write_text(json.dumps(value), encoding='utf-8')
    tasks['tasks'][0]['instruction'] += ' changed after seeing the score'
    (tmp_path / 'tasks.json').write_text(json.dumps(tasks), encoding='utf-8')
    with pytest.raises(ValueError, match='Frozen pack drift'):
        load_pack(tmp_path)


def test_json_grading_rejects_boolean_numeric_confusion_and_allows_numeric_equivalence():
    assert not json_equal({'admit': 1}, {'admit': True})
    assert not json_equal([True], [1])
    assert json_equal({'delay': 1.0}, {'delay': 1})
    assert not json_equal(None, 'None')


def test_frozen_hash_preserves_semantic_mapping_declaration_order():
    assert digest({'first': [], 'second': []}) != digest({'second': [], 'first': []})


@pytest.mark.parametrize('result', [
    ToolResult(ok=False, exit_code=1, error='assertion failure'),
    ToolResult(ok=False, exit_code=-9, error='signal'),
    ToolResult(ok=False, exit_code=2, error='infrastructure'),
    ToolResult(ok=False, error='sandbox_timeout'),
    ToolResult(ok=True, exit_code=0, truncated=True),
])
def test_infrastructure_or_unparseable_execution_never_becomes_a_mutation_kill(result):
    assert classify(result, [1])['classification'] == 'execution_inconclusive'


def test_controller_grades_exact_count_values_and_input_integrity():
    def result(output):
        return ToolResult(ok=True, exit_code=0, output=json.dumps(output))
    assert classify(result([{'value': 1, 'input_unchanged': True}]), [1])['passed']
    assert not classify(result([{'value': 1, 'input_unchanged': False}]), [1])['passed']
    assert classify(result([]), [1])['classification'] == 'protocol_invalid'
    assert classify(result([{'value': 7, 'input_unchanged': True}]), [1])['classification'] == 'contract_rejected'
    assert classify(ToolResult(ok=True, exit_code=0, output='spoof\n[]'), [])['classification'] == 'protocol_invalid'


def test_container_arguments_have_no_network_key_or_host_oracle(tmp_path):
    sandbox = DockerSandbox('sha256:' + 'a' * 64, tmp_path)
    command = sandbox.command('owned-test-name', tmp_path / 'stage', visible=False)
    assert '--network=none' in command and '--read-only' in command
    assert '--cap-drop=ALL' in command and '--user=65534:65534' in command
    assert '--memory=128m' in command and '--pids-limit=32' in command
    assert len([arg for arg in command if arg == '--mount']) == 1
    assert ',dst=/work,readonly' in command[command.index('--mount') + 1]
    assert not any('API_KEY' in arg or 'oracle.json' in arg for arg in command)
    assert '--pull=never' in command


async def test_missing_docker_fails_without_host_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr('repopilot.capsule_sandbox.shutil.which', lambda _: None)
    with pytest.raises(SandboxUnavailable, match='host execution is forbidden'):
        await DockerSandbox('sha256:' + 'a' * 64, tmp_path).preflight()


def test_mutable_image_tag_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='immutable'):
        DockerSandbox('python:latest', tmp_path)


class StubSandbox:
    def __init__(self):
        self.calls = []

    async def execute(self, code, *, visible_tests=None, inputs=None):
        self.calls.append((code, visible_tests, inputs))
        return ToolResult(ok=True, exit_code=0, output='2 visible tests passed')


async def test_router_prevents_test_tampering_shells_and_outside_reads(tmp_path):
    tasks, _, _ = load_pack()
    repo = await materialize(tasks['tasks'][0], tmp_path / 'repo')
    sandbox = StubSandbox()
    router = CapsuleRouter(repo, None, sandbox)
    denied = [
        ('apply_patch', {'path': 'test_visible.py', 'old': 'x', 'new': 'y'}),
        ('apply_patch', {'path': 'solution.py', 'delete': True}),
        ('run_tests', {'command': ['python', '-c', 'print("host")']}),
        ('run_command_safe', {'command': ['python', '-m', 'unittest']}),
        ('read_file', {'path': '../oracle.json'}),
    ]
    for tool, arguments in denied:
        assert not (await router.invoke(tool, arguments)).ok
    assert sandbox.calls == []
    assert (await router.invoke('run_tests', {'command': VISIBLE_COMMAND})).ok
    assert len(sandbox.calls) == 1
    assert 'oracle' not in sandbox.calls[0][1]


def test_ledger_reserves_durably_and_cannot_overwrite_prior_run(tmp_path):
    path = tmp_path / 'calls.jsonl'
    ledger = CallLedger(path)
    try:
        call = ledger.reserve('trial', [{'role': 'user', 'content': 'repair'}], 100)
        entry = json.loads(path.read_text())
        assert entry['call_id'] == call and entry['event'] == 'reserved' and entry['usage'] is None
        with pytest.raises(FileExistsError):
            CallLedger(path)
    finally:
        ledger.file.close()


async def test_failed_or_interrupted_api_usage_stops_batch_no_auto_retry(tmp_path):
    class Failed:
        async def complete(self, messages, max_tokens):
            raise ProviderError('provider_timeout_outcome_unknown')
    ledger = CallLedger(tmp_path / 'calls.jsonl')
    provider = LedgerProvider(Failed(), ledger, 'failure')
    try:
        with pytest.raises(ProviderError, match='provider_timeout'):
            await provider.complete([], 4000)
        with pytest.raises(ProviderError, match='unknown_billed_usage'):
            await provider.complete([], 4000)
        entries = [json.loads(line) for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
        assert [entry['event'] for entry in entries] == ['reserved', 'outcome_unknown']
        assert provider.calls == ledger.calls == 1
        assert entries[0]['max_output_tokens'] == 1536
    finally:
        ledger.file.close()


async def test_cancelled_api_reservation_retains_unknown_usage(tmp_path):
    class Cancelled:
        async def complete(self, messages, max_tokens):
            raise asyncio.CancelledError
    ledger = CallLedger(tmp_path / 'calls.jsonl')
    try:
        with pytest.raises(asyncio.CancelledError):
            await LedgerProvider(Cancelled(), ledger, 'cancelled').complete([], 100)
        assert ledger.unknown_usage and ledger.calls == 1
        assert 'outcome_unknown' in (tmp_path / 'calls.jsonl').read_text()
    finally:
        ledger.file.close()


async def test_call_caps_count_attempts_and_observed_usage(tmp_path):
    class Observed:
        async def complete(self, messages, max_tokens):
            return ModelReply(action=Action(kind='finish', summary='done'),
                              usage=Usage(input_tokens=17, output_tokens=3))
    ledger = CallLedger(tmp_path / 'calls.jsonl')
    provider = LedgerProvider(Observed(), ledger, 'one')
    try:
        for _ in range(6):
            await provider.complete([], 4000)
        with pytest.raises(ProviderError, match='trial_call_budget'):
            await provider.complete([], 4000)
        assert ledger.observed_tokens == 120 and ledger.calls == 6
        ledger.calls = LIMITS['total_calls']
        with pytest.raises(ProviderError, match='batch_call_budget'):
            ledger.reserve('another', [], 10)
    finally:
        ledger.file.close()


def test_observed_token_budget_refuses_next_reservation(tmp_path):
    ledger = CallLedger(tmp_path / 'calls.jsonl')
    try:
        ledger.observed_tokens = LIMITS['observed_tokens_total']
        with pytest.raises(ProviderError, match='batch_token_budget'):
            ledger.reserve('trial', [], 100)
        assert ledger.calls == 0
    finally:
        ledger.file.close()


async def test_dry_run_performs_no_provider_or_container_setup(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected setup or paid call')
    monkeypatch.setattr('repopilot.capsule_eval.OpenAIProvider', forbidden)
    monkeypatch.setattr('repopilot.capsule_eval.DockerSandbox', forbidden)
    args = argparse.Namespace(execute=False, controls=False, image=None, expected_commit=None,
                              data=tmp_path / 'run', output=tmp_path / 'report.json')
    report = await main_async(args)
    assert report['status'] == 'dry_run' and report['provider_calls'] == 0
    assert not args.data.exists()


async def test_full_harness_uses_restricted_adapter_and_never_sends_oracle(tmp_path):
    tasks, oracle, _ = load_pack()
    task = tasks['tasks'][0]
    marker = 'withheld-external-oracle-canary-94723'
    (tmp_path / 'oracle.txt').write_text(marker)
    replies = [
        Action(kind='tool', summary='Reproduce', tool='run_tests', arguments={'command': VISIBLE_COMMAND}),
        Action(kind='tool', summary='Repair', tool='apply_patch', arguments={
            'path': 'solution.py', 'old': task['initial'], 'new': oracle['tasks'][task['id']]['reference']}),
        Action(kind='finish', summary='Submit for independent checking'),
    ]
    class Capture(FakeModelProvider):
        async def complete(self, messages, max_tokens):
            assert marker not in json.dumps(messages) and 'oracle.json' not in json.dumps(messages)
            return await super().complete(messages, max_tokens)
    ledger = CallLedger(tmp_path / 'calls.jsonl')
    sandbox = StubSandbox()
    try:
        row = await run_trial(task, 'compact', tmp_path / 'run', sandbox, ledger, Capture(replies))
        assert row['actor_status'] == 'succeeded' and row['original_files_preserved']
        assert len(sandbox.calls) == 2 and row['provider_calls'] == 3
        assert row['task']['request']['allow_repository_code'] is False
        assert row['task']['request']['budget']['provider_retries'] == 0
        assert Path(row['task']['workspace']).parent != tmp_path
    finally:
        ledger.file.close()
