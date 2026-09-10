from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def now() -> str:
    return datetime.now(UTC).isoformat()


class State(StrEnum):
    UNDERSTAND = "UNDERSTAND"
    PLAN = "PLAN"
    EXECUTE = "EXECUTE"
    VERIFY = "VERIFY"
    REPAIR = "REPAIR"
    FINISH = "FINISH"
    FAILED = "FAILED"


class Budget(BaseModel):
    max_steps: int = Field(default=24, ge=1, le=100)
    timeout_seconds: float = Field(default=120, gt=0, le=1800)
    max_tokens: int = Field(default=40000, ge=64, le=1000000)
    max_cost_usd: float | None = Field(default=None, gt=0, le=100)
    max_repairs: int = Field(default=2, ge=0, le=5)
    provider_retries: int = Field(default=2, ge=0, le=3)
    context_tokens: int = Field(default=6000, ge=64, le=32000)


class Check(BaseModel):
    name: str
    command: list[str] = Field(min_length=1, max_length=20)
    layer: Literal["syntax", "unit", "integration", "repository", "acceptance"] = "unit"


class Acceptance(BaseModel):
    checks: list[Check] = Field(default_factory=list)
    expected_files: list[str] = Field(default_factory=list)
    contains: dict[str, list[str]] = Field(default_factory=dict)
    require_diff: bool = True


class TaskRequest(BaseModel):
    repository: str
    task: str = Field(min_length=3, max_length=8000)
    ref: str = "HEAD"
    provider: Literal["fake", "openai", "replay"] = "fake"
    skill: str | None = "bug-fix"
    context_strategy: Literal["naive", "structured"] = "structured"
    memory_enabled: bool = True
    transport: Literal["native", "mcp"] = "native"
    budget: Budget = Field(default_factory=Budget)
    acceptance: Acceptance = Field(default_factory=Acceptance)
    replay_id: str | None = None
    allow_repository_code: bool = False
    use_verifier: bool = True
    use_context: bool = True
    single_shot: bool = False


class Action(BaseModel):
    kind: Literal["plan", "tool", "finish"]
    summary: str = Field(max_length=2000)
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    plan: list[str] = Field(default_factory=list)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None


class ModelReply(BaseModel):
    action: Action
    usage: Usage = Field(default_factory=Usage)


class ToolResult(BaseModel):
    ok: bool
    output: str = ""
    error: str | None = None
    exit_code: int | None = None
    truncated: bool = False
    duration_ms: float = 0
    requires_approval: bool = False


class TraceEvent(BaseModel):
    sequence: int = 0
    task_id: str
    timestamp: str = Field(default_factory=now)
    state: State
    kind: str
    summary: str
    tool: str | None = None
    transport: str | None = None
    input: dict[str, Any] | None = None
    result: ToolResult | None = None
    usage: Usage | None = None
    duration_ms: float = 0


class TaskRecord(BaseModel):
    task_id: str
    status: str = "queued"
    state: State = State.UNDERSTAND
    created_at: str = Field(default_factory=now)
    finished_at: str | None = None
    repository: str
    repository_commit: str = ""
    workspace: str | None = None
    request: TaskRequest
    budget: Budget
    step_count: int = 0
    repair_count: int = 0
    trace: list[TraceEvent] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    working_memory: dict[str, Any] = Field(
        default_factory=lambda: {"plan": [], "observations": [], "failures": []}
    )
    final_diff: str = ""
    test_result: dict[str, Any] | None = None
    usage: Usage = Field(default_factory=Usage)
    error: str | None = None
    evidence_label: str = "harness-demonstration"
    latency_ms: float = 0


class MemoryEntry(BaseModel):
    id: str
    kind: Literal["episodic", "lesson"]
    repository: str
    commit: str
    content: str
    task_id: str
    provenance: list[dict[str, Any]]
    trusted: bool = False
    valid: bool = True
    created_at: str = Field(default_factory=now)
