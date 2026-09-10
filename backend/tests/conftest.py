from pathlib import Path

import pytest
from repopilot.demo import create_demo_repository
from repopilot.harness import Harness

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def repo(tmp_path):
    return await create_demo_repository(tmp_path / "repository")


@pytest.fixture
def harness(tmp_path):
    return Harness(tmp_path / "data", tmp_path, ROOT / "skills")
