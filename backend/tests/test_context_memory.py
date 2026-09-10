from uuid import uuid4

import pytest
from repopilot.context import ContextBuilder
from repopilot.models import MemoryEntry
from repopilot.store import SQLiteStore
from repopilot.tools import ToolRouter


def test_structured_retrieval_prefers_relevant_symbol(tmp_path):
    (tmp_path / "a.py").write_text("irrelevant = 1\n" * 100)
    (tmp_path / "z.py").write_text(
        "def clamp(value, low, high):\n    return max(low, min(high, value))\n"
    )
    structured = ContextBuilder(tmp_path, 130, "structured").build("clamp boundary")
    naive = ContextBuilder(tmp_path, 130, "naive").build("clamp boundary")
    assert "z.py" in structured["retrieved_files"]
    assert structured["context_tokens"] <= 130
    assert structured["discarded_context"]
    assert structured["strategy"] != naive["strategy"]


def test_context_records_failures_and_redacts_secrets(tmp_path):
    (tmp_path / "README.md").write_text("Hello")
    value = ContextBuilder(tmp_path, 800).build(
        "failure", failures=["test exit 1 sk-abcdefghijklmnopqrstuvwxyz"]
    )
    assert any(c["source"] == "failing-test-output" for c in value["retrieved_chunks"])
    assert "sk-abcdefghijkl" not in str(value)


def test_memory_scope_provenance_and_invalidation(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    entry = MemoryEntry(
        id=str(uuid4()),
        kind="lesson",
        repository="repo",
        commit="abc",
        content="pytest passed",
        task_id="task",
        provenance=[{"trace_sequence": 1, "exit_code": 0}],
        trusted=True,
    )
    store.add_memory(entry)
    assert store.retrieve("repo", "abc", "pytest")[0].id == entry.id
    assert store.retrieve("repo", "other", "pytest") == []
    assert store.retrieve("other", "abc", "pytest") == []
    assert store.invalidate(entry.id)
    assert store.retrieve("repo", "abc", "pytest") == []


def test_untrusted_guess_is_never_retrieved(tmp_path):
    store = SQLiteStore(tmp_path / "memory.sqlite")
    entry = MemoryEntry(
        id="guess",
        kind="lesson",
        repository="r",
        commit="c",
        content="This probably uses Jest",
        task_id="t",
        provenance=[],
        trusted=False,
    )
    store.add_memory(entry)
    assert store.retrieve("r", "c", "Jest") == []
    entry.trusted = True
    with pytest.raises(ValueError, match="provenance"):
        store.add_memory(entry)


async def test_code_review_skill_really_denies_edits(tmp_path):
    router = ToolRouter(tmp_path, allowed_tools=["read_file", "git_diff"])
    result = await router.invoke("apply_patch", {"path": "x.py", "new": "x=1"})
    assert not result.ok and not (tmp_path / "x.py").exists()
