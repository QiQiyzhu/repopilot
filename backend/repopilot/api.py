from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config import PROJECT_ROOT
from .demo import create_demo_repository
from .harness import TERMINAL, Harness
from .models import MemoryEntry, TaskRecord, TaskRequest
from .skills import SkillDefinition


class ApprovalRequest(BaseModel):
    approved: bool


def create_app(data: Path | None = None, repository_root: Path | None = None) -> FastAPI:
    data = data or Path(os.environ.get("REPOPILOT_DATA", ".repopilot"))
    repository_root = repository_root or Path(os.environ.get("REPOPILOT_REPO_ROOT", "."))
    harness = Harness(data, repository_root, PROJECT_ROOT / "skills")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        harness.recover_interrupted()
        app.state.demo_repository = str(await create_demo_repository(data / "demo-repository"))
        yield
        for task_id in list(harness.jobs):
            await harness.cancel(task_id)

    app = FastAPI(title="RepoPilot", version="0.1.0", lifespan=lifespan)
    app.state.harness = harness
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization", "Last-Event-ID"],
    )

    @app.middleware("http")
    async def local_boundary(request: Request, call_next: Any) -> Any:
        from fastapi.responses import JSONResponse

        origin = request.headers.get("origin")
        allowed = {
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        }
        if origin and origin not in allowed:
            return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
        token = os.environ.get("REPOPILOT_API_TOKEN")
        if token and request.headers.get("authorization") != "Bearer " + token:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        return await call_next(request)

    def get_task(task_id: str) -> Any:
        task = harness.store.get_task(task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        return task

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": "0.1.0",
            "demo_repository": getattr(app.state, "demo_repository", None),
            "repository_root": str(repository_root.resolve()),
            "real_provider_configured": bool(
                os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_MODEL")
            ),
            "default_provider": "fake",
            "sandbox": "application-boundary; trusted-repository-code only",
        }

    @app.post("/tasks", status_code=202, response_model=TaskRecord)
    async def submit(request: TaskRequest) -> Any:
        try:
            return await harness.submit(request)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/tasks", response_model=list[TaskRecord])
    async def list_tasks() -> Any:
        return harness.store.list_tasks()

    @app.get("/tasks/{task_id}", response_model=TaskRecord)
    async def task(task_id: str) -> Any:
        return get_task(task_id)

    @app.post("/tasks/{task_id}/cancel")
    async def cancel(task_id: str) -> dict[str, Any]:
        get_task(task_id)
        return {"cancelled": await harness.cancel(task_id)}

    @app.post("/tasks/{task_id}/retry", status_code=202, response_model=TaskRecord)
    async def retry(task_id: str) -> Any:
        original = get_task(task_id)
        if original.status not in TERMINAL:
            raise HTTPException(409, "Only a terminal task can be retried")
        return await harness.submit(original.request)

    @app.post("/tasks/{task_id}/approval")
    async def approval(task_id: str, request: ApprovalRequest) -> dict[str, Any]:
        get_task(task_id)
        if not harness.approve(task_id, request.approved):
            raise HTTPException(409, "No destructive action is awaiting approval")
        return {"recorded": True, "approved": request.approved}

    @app.get("/tasks/{task_id}/context")
    async def context(task_id: str) -> Any:
        return get_task(task_id).context

    @app.get("/tasks/{task_id}/events")
    async def events(task_id: str, request: Request, after: int = 0) -> StreamingResponse:
        get_task(task_id)
        try:
            cursor = max(0, after, int(request.headers.get("last-event-id", "0")))
        except ValueError as error:
            raise HTTPException(422, "Invalid Last-Event-ID") from error

        async def stream() -> AsyncIterator[str]:
            nonlocal cursor
            heartbeat = 0
            while not await request.is_disconnected():
                rows = harness.store.events(task_id, cursor)
                for event in rows:
                    cursor = event.sequence
                    yield f"id: {event.sequence}\nevent: trace\ndata: {event.model_dump_json()}\n\n"
                current = harness.store.get_task(task_id)
                if current and current.status in TERMINAL:
                    yield (
                        "event: done\ndata: "
                        + json.dumps({"task_id": task_id, "status": current.status})
                        + "\n\n"
                    )
                    break
                heartbeat += 1
                if heartbeat % 40 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.25)
            # Disconnect stops delivery only. Explicit /cancel owns task cancellation.

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/dashboard")
    async def dashboard() -> Any:
        return harness.dashboard()

    @app.get("/skills", response_model=list[SkillDefinition])
    async def skills() -> Any:
        return list(harness.registry.skills.values())

    @app.get("/memory", response_model=list[MemoryEntry])
    async def memory() -> Any:
        return harness.store.all_memory()

    @app.post("/memory/{memory_id}/invalidate")
    async def invalidate(memory_id: str) -> dict[str, bool]:
        return {"invalidated": harness.store.invalidate(memory_id)}

    @app.get("/evaluations")
    async def evaluations() -> Any:
        reports = PROJECT_ROOT / "evaluation" / "results"
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(reports.glob("*.json"))]

    return app


app = create_app()
