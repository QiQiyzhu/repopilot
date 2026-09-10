# Architecture

RepoPilot has one Python process, a static React client and SQLite. The process owns in-memory asyncio jobs; SQLite stores durable task records, ordered events and scoped memory. PostgreSQL can implement the repository protocols later, but no external database is required.

`interfaces.py` defines ModelProvider, Tool, Skill, ContextProvider, MemoryStore, Evaluator, Workspace and TraceStore. `SQLiteStore` implements the storage boundaries. `TaskRecord` and `TraceEvent` are Pydantic contracts and the API publishes its OpenAPI schema.

1. The API validates task parameters, repository root and skill selection before returning 202.
2. The harness archives the requested committed ref, rejects unsafe archive members, and creates a fresh Git baseline. It preserves the source checkout.
3. A provider emits a validated Action. Plans, tool invocations and finish requests are explicit variants.
4. The skill controls tools, reproduction ordering and verification requirements. The router performs boundary checks before execution.
5. The verifier independently runs checks, reads the actual diff and confirms expected files/content. Failed checks enter bounded REPAIR.
6. Every transition/action/tool result is persisted. SSE clients replay from their Last-Event-ID and disconnect independently from execution.
7. Verified results can produce provenance-backed memory for that exact repository/commit. No model-only guess becomes a trusted lesson.

## Operational choices

Two local tasks may execute concurrently. A task has a wall-clock deadline including queued/setup time. Explicit cancellation terminates child process trees. Source checkout isolation uses archives rather than shared Git worktrees, avoiding shared-index/hook accidents. It uses more disk and does not preserve uncommitted changes.

SQLite uses WAL, parameterized queries and short transactions. Storage calls are synchronous and small; repository retrieval is moved to a worker thread. This is an explainable local lab, not a high-throughput distributed scheduler. Restarted running jobs are marked failed rather than silently resumed; retry creates a new workspace and task ID.

## Ports and deployment

Native Vite :5174 proxies /api to FastAPI :8000. Compose uses nginx :8080 with buffering disabled for SSE. Backend is loopback-published, non-root, with a writable named workspace volume. Repository code and subprocesses must be trusted in host mode. A stronger per-job sandbox is required before accepting untrusted users or repositories.

## External references

The implementation uses the [official MCP Python v1 SDK](https://py.sdk.modelcontextprotocol.io/v1/) and its initialized ClientSession/stdio transport. The real adapter calls the documented [OpenAI Chat Completions endpoint](https://platform.openai.com/docs/api-reference/chat); JSON mode is followed by local Pydantic validation. No claim is made that JSON mode alone guarantees valid actions.
