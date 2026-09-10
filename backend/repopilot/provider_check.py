"""An offline configuration check and one bounded, explicitly opted-in HTTP probe.

The probe sends no repository context and executes no actions. A valid response is
connectivity/schema evidence, never evidence of coding ability or benchmark success.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import PROJECT_ROOT
from .models import now
from .providers import OpenAIProvider, ProviderError, RemoteConfig


def configuration_check() -> dict[str, Any]:
    try:
        return RemoteConfig.from_environment().public_status()
    except ProviderError as error:
        return {"configured": False, "network_checked": False, "error": str(error)}


def source_receipt() -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    state = git("status", "--porcelain")
    return {
        "git_commit": git("rev-parse", "HEAD"),
        "working_tree_dirty": bool(state) if state is not None else None,
        "source_sha256_lf": {
            name: hashlib.sha256(
                (Path(__file__).parent / name).read_text(encoding="utf-8").encode()
            ).hexdigest()
            for name in ["providers.py", "provider_check.py"]
        },
    }


async def smoke(
    *, confirm_paid_api: bool, max_output_tokens: int = 256, provider: OpenAIProvider | None = None
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "recorded_at": now(),
        "evidence_type": "remote-provider-smoke"
        if provider is None
        else "injected-transport-contract",
        "is_model_benchmark": False,
        "provider_calls_attempted": 0,
        "validated_responses": 0,
        "usage": None,
        "source": source_receipt(),
        "limits": {
            "max_calls": 1,
            "retries": 0,
            "max_output_tokens": max_output_tokens,
            "repository_bytes_sent": 0,
            "tools_executed": 0,
        },
        "limitation": "One schema/nonce response does not measure coding ability. Failed or interrupted calls may be billed; absent usage is unknown, not zero. Cost is an estimate only when operator-supplied rates are configured.",
    }
    if not confirm_paid_api:
        return {
            **report,
            "status": "not_authorized",
            "error": "Explicit --execute (or --confirm-paid-api) required",
        }
    if type(max_output_tokens) is not int or not 64 <= max_output_tokens <= 512:
        return {
            **report,
            "status": "invalid_budget",
            "error": "Smoke output budget must be in [64, 512]",
        }
    try:
        remote = provider or OpenAIProvider()
    except ProviderError as error:
        return {**report, "status": "not_configured", "error": str(error)}
    report["configuration"] = remote.config.public_status()
    nonce = "repopilot-smoke:" + uuid4().hex
    messages = [
        {
            "role": "system",
            "content": "Return one JSON object only. Use exactly the keys kind, summary, tool, arguments and plan. Do not explain or execute any action.",
        },
        {
            "role": "user",
            "content": json.dumps(
                {"kind": "finish", "summary": nonce, "tool": None, "arguments": {}, "plan": []}
            ),
        },
    ]
    report["request_sha256"] = hashlib.sha256(
        json.dumps(messages, sort_keys=True).encode()
    ).hexdigest()
    started = time.monotonic()
    report["provider_calls_attempted"] = 1
    try:
        async with asyncio.timeout(remote.config.timeout_seconds):
            reply = await remote.complete(messages, max_output_tokens)
        action = reply.action
        matches = (
            action.kind == "finish"
            and action.summary == nonce
            and action.tool is None
            and not action.arguments
            and not action.plan
        )
        report.update(
            status="passed" if matches else "failed",
            validated_responses=1,
            checks={"action_schema_valid": True, "nonce_contract": matches},
            usage=reply.usage.model_dump(),
            provider=reply.provider_metadata,
        )
        # Never store arbitrary provider output, including unsolicited content or reasoning.
    except (ProviderError, TimeoutError) as error:
        report.update(
            status="failed",
            error=str(error)
            if isinstance(error, ProviderError)
            else "provider_timeout_outcome_unknown",
        )
    report["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
    return report


def write_report(report: dict[str, Any], output: str | None) -> None:
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
