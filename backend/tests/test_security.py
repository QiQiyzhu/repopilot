import asyncio
import sys

import pytest
from repopilot.security import (
    BoundaryError,
    child_environment,
    redact,
    resolve_inside,
    run_process,
    validate_command,
)
from repopilot.tools import ToolRouter


@pytest.mark.parametrize(
    "path",
    [
        "../outside.txt",
        "x/../../outside",
        ".env",
        ".env.local",
        ".git/config",
        "C:/Windows/win.ini",
        "x:stream",
        "/etc/passwd",
        "x\\..\\a",
        ".ssh/id_rsa",
    ],
)
def test_path_boundary(tmp_path, path):
    with pytest.raises(BoundaryError):
        resolve_inside(tmp_path, path)


def test_symlinks_rejected(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Host disallows symlink creation without elevation")
    with pytest.raises(BoundaryError):
        resolve_inside(tmp_path, "link/file.py")


@pytest.mark.parametrize(
    "command",
    [
        ["rm", "-rf", "."],
        ["git", "reset", "--hard"],
        ["python", "-c", "print(1)"],
        ["node", "-e", "process.exit()"],
        ["npm", "install"],
        ["git", "-c", "alias.x=!rm -rf .", "x"],
        ["python", "-m", "pytest", "--override-ini=x"],
        ["python", "-m", "pytest", "../../x"],
        ["git", "status;curl", "https://x"],
    ],
)
def test_command_allowlist(tmp_path, command):
    with pytest.raises(BoundaryError):
        validate_command(command, tmp_path, True)


def test_tests_require_trust(tmp_path):
    with pytest.raises(BoundaryError, match="Repository tests execute code"):
        validate_command(["python", "-m", "pytest", "-q"], tmp_path, False)


def test_secrets_are_redacted_and_not_in_child_environment(monkeypatch):
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    assert secret not in redact("key=" + secret)
    assert "[REDACTED]" in redact("Bearer abcdefghijk")
    assert "OPENAI_API_KEY" not in child_environment()
    assert "DEEPSEEK_API_KEY" not in child_environment()


async def test_timeout_kills_process(tmp_path):
    result = await run_process(
        [sys.executable, "-c", "import time; time.sleep(10)"], tmp_path, timeout=0.1
    )
    assert not result.ok and result.error == "command_timeout"
    assert result.duration_ms < 5000


async def test_output_limit_drains_noisy_child(tmp_path):
    result = await run_process(
        [sys.executable, "-c", "print('x' * 200000)"], tmp_path, output_limit=400
    )
    assert result.ok and result.truncated
    assert len(result.output) == 400


async def test_cancel_stops_child(tmp_path):
    task = asyncio.create_task(
        run_process([sys.executable, "-c", "import time;time.sleep(10)"], tmp_path)
    )
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_patch_is_exact_and_deletion_requires_approval(tmp_path):
    (tmp_path / "file.py").write_text("a = 1\na = 1\n", encoding="utf-8")
    router = ToolRouter(tmp_path)
    result = await router.invoke("apply_patch", {"path": "file.py", "old": "a = 1", "new": "a = 2"})
    assert not result.ok
    deletion = await router.invoke("apply_patch", {"path": "file.py", "delete": True})
    assert deletion.requires_approval and (tmp_path / "file.py").exists()
    router.approved_deletions.add("file.py")
    assert (await router.invoke("apply_patch", {"path": "file.py", "delete": True})).ok
    assert not (tmp_path / "file.py").exists()


async def test_router_does_not_read_secrets(tmp_path):
    (tmp_path / ".env").write_text("secret", encoding="utf-8")
    result = await ToolRouter(tmp_path).invoke("read_file", {"path": ".env"})
    assert not result.ok and "secret" not in result.output


def test_redacted_structures_preserve_json_envelopes():
    import json

    from repopilot.security import redact_data

    value = {"input": "password=private-value", "nested": ["sk-abcdefghijklmnopqrstuvwxyz"]}
    result = redact_data(value)
    assert json.loads(json.dumps(result)) == result
    assert "private-value" not in str(result)


async def test_patch_preserves_crlf_to_keep_diff_scoped(tmp_path):
    file = tmp_path / "sample.py"
    file.write_bytes(b"a = 1\r\nb = 2\r\n")
    result = await ToolRouter(tmp_path).invoke(
        "apply_patch", {"path": "sample.py", "old": "a = 1", "new": "a = 3"}
    )
    assert result.ok
    assert file.read_bytes() == b"a = 3\r\nb = 2\r\n"
