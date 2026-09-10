from pathlib import Path

from .security import run_process


async def create_demo_repository(root: Path) -> Path:
    """A deliberately broken, clearly labelled fixture; never masquerades as ARC//SHIFT."""
    root.mkdir(parents=True, exist_ok=True)
    if (root / ".git").exists():
        return root
    (root / "calculator.py").write_text(
        '''"""Deliberately broken fixture used only for deterministic harness validation."""
def clamp(value, low, high):
    return max(low, max(high, value))
''',
        encoding="utf-8",
    )
    (root / "test_calculator.py").write_text(
        """from calculator import clamp

def test_inside():
    assert clamp(5, 0, 10) == 5

def test_below():
    assert clamp(-3, 0, 10) == 0

def test_above():
    assert clamp(12, 0, 10) == 10
""",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# RepoPilot deterministic demonstration fixture\nA clamp bug, three real pytest checks, and one exact scripted repair. This is not a language-model benchmark.\n",
        encoding="utf-8",
    )
    for command in [
        ["git", "init", "--quiet"],
        ["git", "add", "."],
        [
            "git",
            "-c",
            "user.name=RepoPilot",
            "-c",
            "user.email=repopilot@localhost",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "Deliberately broken demo fixture",
        ],
    ]:
        result = await run_process(command, root)
        if not result.ok:
            raise RuntimeError(result.output)
    return root
