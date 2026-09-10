from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .models import Action, ModelReply, Usage


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class RemoteConfig:
    key: str = field(repr=False)
    model: str
    base_url: str
    flavor: str
    timeout_seconds: float
    input_rate: float | None
    output_rate: float | None

    @classmethod
    def from_environment(cls) -> RemoteConfig:
        flavor = os.environ.get("REPOPILOT_PROVIDER_FLAVOR", "openai").strip()
        if flavor not in {"openai", "deepseek", "qwen", "compatible"}:
            raise ProviderError("REPOPILOT_PROVIDER_FLAVOR must be openai, deepseek, qwen or compatible")
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        model = os.environ.get("OPENAI_MODEL", "").strip()
        base = os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/")
        if flavor == "deepseek":
            key = os.environ.get("DEEPSEEK_API_KEY", "").strip() or key
            model = os.environ.get("DEEPSEEK_MODEL", "").strip() or model
            base = os.environ.get("DEEPSEEK_BASE_URL", "").strip().rstrip("/") or base
            if not base:
                base = "https://api.deepseek.com"
        if not base and flavor == "openai":
            base = "https://api.openai.com/v1"
        if not key or not model:
            raise ProviderError(
                "Set a server API key and explicit model: DEEPSEEK_API_KEY / DEEPSEEK_MODEL for deepseek, or OPENAI_API_KEY / OPENAI_MODEL"
            )
        try:
            url = urlsplit(base)
            explicit_loopback = (
                url.scheme == "http"
                and url.hostname in {"127.0.0.1", "::1", "localhost"}
                and url.port is not None
            )
            if (
                not url.hostname
                or not (url.scheme == "https" or explicit_loopback)
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
                or any(char in base for char in "{}\\\r\n\t ")
            ):
                raise ValueError
        except ValueError:
            raise ProviderError(
                "OPENAI_BASE_URL must be a complete HTTPS base URL (or explicit loopback port), without credentials, query or placeholders"
            ) from None
        if flavor == "deepseek" and base not in {
            "https://api.deepseek.com", "https://api.deepseek.com/v1"
        }:
            raise ProviderError("DeepSeek flavor requires the official HTTPS API base URL")
        if len(model) > 200 or any(char.isspace() for char in model) or key in model:
            raise ProviderError("Provider model must be a non-secret identifier of at most 200 characters")
        try:
            timeout = float(os.environ.get("REPOPILOT_PROVIDER_TIMEOUT_SECONDS", "45"))
            if not math.isfinite(timeout) or not 0 < timeout <= 120:
                raise ValueError
            rates = [
                os.environ.get(f"REPOPILOT_{side}_USD_PER_MILLION", "")
                for side in ["INPUT", "OUTPUT"]
            ]
            if bool(rates[0]) != bool(rates[1]):
                raise ValueError
            parsed = [float(rate) if rate else None for rate in rates]
            if any(rate is not None and (not math.isfinite(rate) or rate < 0) for rate in parsed):
                raise ValueError
        except ValueError:
            raise ProviderError(
                "Provider timeout must be finite in (0, 120]; both optional USD rates must be finite and nonnegative"
            ) from None
        return cls(key, model, base, flavor, timeout, parsed[0], parsed[1])

    def public_status(self) -> dict[str, Any]:
        return {
            "configured": True,
            "credentials_present": True,
            "flavor": self.flavor,
            "model": self.model,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "output_token_parameter": "max_completion_tokens"
            if self.flavor == "openai"
            else "max_tokens",
            "thinking": "disabled" if self.flavor in {"qwen", "deepseek"} else "provider-default",
            "cost_rates_configured": self.input_rate is not None,
            "network_checked": False,
        }


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
        self.config = RemoteConfig.from_environment()
        self.key, self.model, self.base_url = (
            self.config.key,
            self.config.model,
            self.config.base_url,
        )
        self.client = client

    async def complete(self, messages: list[dict[str, Any]], max_tokens: int) -> ModelReply:
        if type(max_tokens) is not int or max_tokens <= 0:
            raise ProviderError("provider_invalid_output_budget")
        token_parameter = (
            "max_completion_tokens" if self.config.flavor == "openai" else "max_tokens"
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            token_parameter: min(max_tokens, 4000),
            "response_format": {"type": "json_object"},
        }
        if self.config.flavor == "qwen":
            payload["enable_thinking"] = False
        elif self.config.flavor == "deepseek":
            payload["thinking"] = {"type": "disabled"}
        own_client = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=self.config.timeout_seconds, follow_redirects=False
        )
        try:
            response = await client.post(
                self.base_url + "/chat/completions",
                headers={"Authorization": "Bearer " + self.key},
                json=payload,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise ProviderError(
                    f"provider_http_{response.status_code}",
                    retryable=response.status_code in {408, 429, 500, 502, 503, 504},
                )
            body = response.json()
            choice = body["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ProviderError("provider_output_truncated")
            if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
                raise ProviderError("provider_output_not_complete")
            action = Action.model_validate_json(choice["message"]["content"])
            usage = body["usage"]
            input_tokens, output_tokens = (
                usage["prompt_tokens"],
                usage["completion_tokens"],
            )
            if any(type(value) is not int or value < 0 for value in (input_tokens, output_tokens)):
                raise ProviderError("provider_invalid_usage")
            rates = self.config.input_rate, self.config.output_rate
            cost = (
                (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000
                if rates[0] is not None and rates[1] is not None
                else None
            )
            metadata = {
                "requested_model": self.model,
                "resolved_model": body.get("model"),
                "request_id": response.headers.get("x-request-id") or body.get("id"),
                "flavor": self.config.flavor,
            }
            # Only bounded scalar provenance; never raw response/error bodies or reasoning content.
            safe_metadata = {
                k: v
                for k, v in metadata.items()
                if isinstance(v, str) and len(v) <= 200 and self.key not in v
            }
            return ModelReply(
                action=action,
                usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost),
                provider_metadata=safe_metadata,
            )
        except httpx.TimeoutException:
            # A read timeout may have consumed tokens. Do not auto-repeat a billable request.
            raise ProviderError("provider_timeout_outcome_unknown") from None
        except httpx.ConnectError:
            raise ProviderError("provider_connection_failed", retryable=True) from None
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as error:
            raise ProviderError(f"Invalid provider response: {type(error).__name__}") from None
        finally:
            if own_client:
                await client.aclose()
