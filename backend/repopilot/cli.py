from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from .config import PROJECT_ROOT
from .demo import create_demo_repository
from .harness import Harness
from .models import TaskRequest


async def execute(args: argparse.Namespace) -> None:
    data = Path(args.data).resolve()
    if args.command == "demo":
        repository = await create_demo_repository(data / "demo-repository")
        request = TaskRequest(
            repository=str(repository),
            task="Fix clamp so interior and both boundary cases pass",
            allow_repository_code=True,
            transport=args.transport,
        )
        root = data
    else:
        repository = Path(args.repository).resolve()
        root = repository.parent
        request = TaskRequest(
            repository=str(repository),
            task=args.task,
            ref=args.ref,
            provider=args.provider,
            replay_id=args.replay_id,
            transport=args.transport,
            allow_repository_code=args.trust_code,
            skill=args.skill,
        )
    harness = Harness(data, root, PROJECT_ROOT / "skills")
    task = await harness.submit(request)
    await harness.jobs[task.task_id]
    result = harness.store.get_task(task.task_id)
    assert result
    output = result.model_dump_json(indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output, encoding="utf-8")
    print(
        json.dumps(
            {
                "task_id": result.task_id,
                "status": result.status,
                "workspace": result.workspace,
                "steps": result.step_count,
                "evidence_label": result.evidence_label,
                "error": result.error,
            },
            indent=2,
        )
    )
    if result.status != "succeeded":
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RepoPilot: bounded execution with verifiable evidence"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default=os.environ.get("REPOPILOT_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("REPOPILOT_PORT", "8000")))
    for name in ["demo", "run"]:
        p = sub.add_parser(name)
        p.add_argument("--data", default=".repopilot")
        p.add_argument("--transport", choices=["native", "mcp"], default="native")
        p.add_argument("--output")
        if name == "run":
            p.add_argument("repository")
            p.add_argument("task")
            p.add_argument("--provider", choices=["fake", "openai", "replay"], default="fake")
            p.add_argument("--ref", default="HEAD")
            p.add_argument("--replay-id")
            p.add_argument("--skill", default="bug-fix")
            p.add_argument("--trust-code", action="store_true")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("repopilot.api:app", host=args.host, port=args.port)
    else:
        asyncio.run(execute(args))


if __name__ == "__main__":
    main()
