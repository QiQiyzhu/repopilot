from typing import Any, Protocol

from .models import MemoryEntry, ModelReply, TaskRecord, ToolResult, TraceEvent


class ModelProvider(Protocol):
    name: str

    async def complete(self, messages: list[dict[str, Any]], max_tokens: int) -> ModelReply: ...


class Tool(Protocol):
    name: str

    async def invoke(self, arguments: dict[str, Any]) -> ToolResult: ...


class Skill(Protocol):
    name: str
    allowed_tools: list[str]
    workflow: list[str]
    verification: list[str]


class ContextProvider(Protocol):
    def retrieve(self, query: str) -> list[dict[str, Any]]: ...


class MemoryStore(Protocol):
    def retrieve(self, repository: str, commit: str, query: str) -> list[MemoryEntry]: ...
    def add_memory(self, entry: MemoryEntry) -> None: ...
    def invalidate(self, memory_id: str) -> bool: ...


class Workspace(Protocol):
    async def create(self, repository: str, ref: str, task_id: str) -> tuple[str, str]: ...


class TraceStore(Protocol):
    def save_task(self, task: TaskRecord) -> None: ...
    def get_task(self, task_id: str) -> TaskRecord | None: ...
    def list_tasks(self) -> list[TaskRecord]: ...
    def append_event(self, event: TraceEvent) -> TraceEvent: ...


class Evaluator(Protocol):
    async def evaluate(self, task: TaskRecord) -> dict[str, Any]: ...
