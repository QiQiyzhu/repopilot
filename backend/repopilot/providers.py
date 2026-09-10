from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from .models import Action, ModelReply, Usage


class ProviderError(RuntimeError):
    pass


class FakeModelProvider:
    """A scripted test double. It only repairs the included clamp fixture, never a benchmark."""

    name = "fake"

    def __init__(self, actions: list[Action] | None = None):
        self.index = 0
        self.actions = actions or [
            Action(
                kind="plan",
                summary="Deterministic fixture demonstration; no LLM reasoning is being evaluated.",
                plan=[
                    "Read clamp contract",
                    "Reproduce the failing boundary test",
                    "Repair the single comparison",
                    "Run tests and review diff",
                ],
            ),
            Action(
                kind="tool",
                summary="Read the small fixture",
                tool="read_file",
                arguments={"path": "calculator.py"},
            ),
            Action(
                kind="tool",
                summary="Reproduce the checked-in failing boundary test",
                tool="run_tests",
                arguments={"command": ["python", "-m", "pytest", "-q"]},
            ),
            Action(
                kind="tool",
                summary="Repair the fixture's upper bound",
                tool="apply_patch",
                arguments={
                    "path": "calculator.py",
                    "old": "return max(low, max(high, value))",
                    "new": "return max(low, min(high, value))",
                },
            ),
            Action(
                kind="tool",
                summary="Run actual fixture tests",
                tool="run_tests",
                arguments={"command": ["python", "-m", "pytest", "-q"]},
            ),
            Action(kind="tool", summary="Review actual workspace changes", tool="git_diff"),
            Action(
                kind="finish",
                summary="Fixture repair complete; the verifier decides success from process evidence.",
            ),
        ]

    async def complete(self, messages: list[dict[str, Any]], max_tokens: int) -> ModelReply:
        if self.index >= len(self.actions):
            action = Action(
                kind="finish", summary="Deterministic script exhausted; no invented repair."
            )
        else:
            action = self.actions[self.index]
            self.index += 1
        return ModelReply(action=action)


class ReplayProvider:
    name = "replay"

    def __init__(self, recording: Path):
        self.steps = json.loads(recording.read_text(encoding="utf-8"))
        self.index = 0

    async def complete(self, messages: list[dict[str, Any]], max_tokens: int) -> ModelReply:
        if self.index >= len(self.steps):
            raise ProviderError("Replay exhausted; cannot invent the next action")
        step = ModelReply.model_validate(self.steps[self.index])
        self.index += 1
        return step


class OpenAIProvider:
    """Real HTTP adapter. Model/key explicit; errors propagate, no silent fake fallback."""

    name = "openai"

    def __init__(self, *, client: httpx.AsyncClient | None = None):
        self.key = os.environ.get("OPENAI_API_KEY", "")
        self.model = os.environ.get("OPENAI_MODEL", "")
        self.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.client = client
        if not self.key or not self.model:
            raise ProviderError(
                "OPENAI_API_KEY and OPENAI_MODEL must be set for an explicitly requested real-provider run"
            )
        if not self.base_url.startswith("https://") and not self.base_url.startswith(
            "http://127.0.0.1:"
        ):
            raise ProviderError("Provider endpoint must use HTTPS or explicit localhost")

    async def complete(self, messages: list[dict[str, Any]], max_tokens: int) -> ModelReply:
        payload = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": min(max_tokens, 4000),
            "response_format": {"type": "json_object"},
        }
        own_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=45)
        try:
            response = await client.post(
                self.base_url + "/chat/completions",
                headers={"Authorization": "Bearer " + self.key},
                json=payload,
            )
            if response.status_code >= 400:
                raise ProviderError(f"provider_http_{response.status_code}")
            body = response.json()
            choice = body["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ProviderError("provider_output_truncated")
            action = Action.model_validate_json(choice["message"]["content"])
            usage = body.get("usage", {})
            input_tokens, output_tokens = (
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            )
            rates = (
                os.environ.get("REPOPILOT_INPUT_USD_PER_MILLION"),
                os.environ.get("REPOPILOT_OUTPUT_USD_PER_MILLION"),
            )
            cost = (
                (input_tokens * float(rates[0]) + output_tokens * float(rates[1])) / 1_000_000
                if rates[0] and rates[1]
                else None
            )
            return ModelReply(
                action=action,
                usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost),
            )
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as error:
            raise ProviderError(f"Invalid provider response: {type(error).__name__}") from error
        finally:
            if own_client:
                await client.aclose()
