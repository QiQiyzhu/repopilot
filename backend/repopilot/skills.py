from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .tools import TOOL_NAMES


class SkillDefinition(BaseModel):
    name: str
    description: str
    trigger: list[str]
    workflow: list[str]
    allowed_tools: list[str]
    verification: list[str] = Field(min_length=1)
    require_reproduction: bool = False


class SkillRegistry:
    def __init__(self, directory: Path):
        self.skills: dict[str, SkillDefinition] = {}
        for path in sorted(directory.glob("*.md")):
            parts = path.read_text(encoding="utf-8").split("---", 2)
            if len(parts) < 3:
                raise ValueError(f"Skill frontmatter missing: {path.name}")
            skill = SkillDefinition.model_validate(yaml.safe_load(parts[1]))
            if set(skill.allowed_tools) - set(TOOL_NAMES):
                raise ValueError(f"Unknown tool in {skill.name}")
            if skill.name in self.skills:
                raise ValueError("Duplicate skill name")
            self.skills[skill.name] = skill

    def get(self, name: str | None) -> SkillDefinition | None:
        if name is None:
            return None
        if name not in self.skills:
            raise ValueError(f"Unknown skill {name}")
        return self.skills[name]
