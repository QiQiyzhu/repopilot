import json

import httpx
import pytest
from repopilot.provider_check import configuration_check, smoke
from repopilot.providers import OpenAIProvider, ProviderError, RemoteConfig


@pytest.fixture(autouse=True)
def isolated_provider_environment(monkeypatch):
    for name in [
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_BASE_URL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_BASE_URL",
        "REPOPILOT_PROVIDER_FLAVOR",
        "REPOPILOT_PROVIDER_TIMEOUT_SECONDS",
        "REPOPILOT_INPUT_USD_PER_MILLION",
        "REPOPILOT_OUTPUT_USD_PER_MILLION",
    ]:
        monkeypatch.delenv(name, raising=False)


def remote_environment(monkeypatch, flavor="openai"):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-used-on-network")
    monkeypatch.setenv("OPENAI_MODEL", "qwen-plus" if flavor == "qwen" else "test-model")
    monkeypatch.setenv("REPOPILOT_PROVIDER_FLAVOR", flavor)
    if flavor == "deepseek":
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    elif flavor != "openai":
        monkeypatch.setenv(
            "OPENAI_BASE_URL", "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        )


def valid_response(content=None):
    return {
        "id": "response-1",
        "model": "resolved-snapshot",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": content or '{"kind":"finish","summary":"ready"}'},
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


async def test_real_adapter_validates_http_payload_and_usage(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-used-on-network")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("REPOPILOT_INPUT_USD_PER_MILLION", "2")
    monkeypatch.setenv("REPOPILOT_OUTPUT_USD_PER_MILLION", "8")

    def respond(request):
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key-never-used-on-network"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"kind":"finish","summary":"ready","arguments":{},"plan":[]}'
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await OpenAIProvider(client=client).complete(
            [{"role": "user", "content": "test"}], 1000
        )
    assert result.usage.input_tokens == 100
    assert result.usage.cost_usd == pytest.approx(0.00036)


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_provider_errors_do_not_leak_keys(monkeypatch, status):
    monkeypatch.setenv("OPENAI_API_KEY", "private-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="secret body"))
    ) as client:
        with pytest.raises(ProviderError) as error:
            await OpenAIProvider(client=client).complete([], 1000)
    assert str(status) in str(error.value)
    assert "private-test-key" not in str(error.value)


async def test_malformed_provider_action_fails(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
        )
    ) as client:
        with pytest.raises(ProviderError):
            await OpenAIProvider(client=client).complete([], 1000)


@pytest.mark.parametrize("flavor", ["openai", "deepseek", "qwen", "compatible"])
async def test_explicit_vendor_payload_and_provenance(monkeypatch, flavor):
    remote_environment(monkeypatch, flavor)

    def respond(request):
        payload = json.loads(request.content)
        token_parameter = "max_completion_tokens" if flavor == "openai" else "max_tokens"
        assert payload[token_parameter] == 4000
        assert ("enable_thinking" in payload) == (flavor == "qwen")
        if flavor == "qwen":
            assert payload["enable_thinking"] is False
        assert ("thinking" in payload) == (flavor == "deepseek")
        if flavor == "deepseek":
            assert payload["thinking"] == {"type": "disabled"}
            assert request.url == "https://api.deepseek.com/chat/completions"
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json=valid_response(), headers={"x-request-id": "request-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reply = await OpenAIProvider(client=client).complete([], 8000)
    assert reply.provider_metadata["resolved_model"] == "resolved-snapshot"
    assert reply.provider_metadata["request_id"] == "request-1"
    assert reply.usage.cost_usd is None


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v1",
        "https://user:secret@example.com/v1",
        "https://example.com/v1?api_key=secret",
        "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "http://127.0.0.1.evil.test:123/v1",
    ],
)
def test_endpoint_configuration_cannot_send_key_to_ambiguous_url(monkeypatch, url):
    remote_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_BASE_URL", url)
    result = configuration_check()
    assert not result["configured"] and not result["network_checked"]
    assert "secret" not in json.dumps(result) and "never-used" not in json.dumps(result)


def test_configuration_fails_closed_and_redacts_secrets(monkeypatch):
    assert not configuration_check()["configured"]
    remote_environment(monkeypatch, "qwen")
    monkeypatch.delenv("OPENAI_BASE_URL")
    assert not configuration_check()["configured"]
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8123/v1")
    assert configuration_check()["configured"]
    assert "never-used" not in repr(RemoteConfig.from_environment())
    for name, value in [
        ("REPOPILOT_PROVIDER_TIMEOUT_SECONDS", "nan"),
        ("REPOPILOT_INPUT_USD_PER_MILLION", "-1"),
    ]:
        monkeypatch.setenv(name, value)
        assert not configuration_check()["configured"]
        monkeypatch.delenv(name)


@pytest.mark.parametrize(
    "problem",
    ["empty_choices", "truncated", "filtered", "refusal", "empty_content", "usage_missing", "negative_usage", "string_usage"],
)
async def test_unusable_response_never_becomes_a_zero_cost_success(monkeypatch, problem):
    remote_environment(monkeypatch)
    body = valid_response()
    if problem == "empty_choices":
        body["choices"] = []
    elif problem in {"truncated", "filtered"}:
        body["choices"][0]["finish_reason"] = (
            "length" if problem == "truncated" else "content_filter"
        )
    elif problem == "usage_missing":
        body.pop("usage")
    elif problem == "refusal":
        body["choices"][0]["message"]["refusal"] = "Cannot comply"
    elif problem == "empty_content":
        body["choices"][0]["message"]["content"] = ""
    else:
        body["usage"]["prompt_tokens"] = -1 if problem == "negative_usage" else "100"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as client:
        with pytest.raises(ProviderError) as caught:
            await OpenAIProvider(client=client).complete([], 256)
    assert not caught.value.retryable


@pytest.mark.parametrize("status,retryable", [(302, False), (401, False), (429, True), (503, True)])
async def test_only_explicit_transient_statuses_allow_retry(monkeypatch, status, retryable):
    remote_environment(monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="private-body"))
    ) as client:
        with pytest.raises(ProviderError) as caught:
            await OpenAIProvider(client=client).complete([], 256)
    assert caught.value.retryable is retryable
    assert "private-body" not in str(caught.value)


async def test_timeout_has_unknown_billable_outcome_and_no_automatic_retry(monkeypatch):
    remote_environment(monkeypatch)

    def timeout(request):
        raise httpx.ReadTimeout("private URL and headers", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(ProviderError) as caught:
            await OpenAIProvider(client=client).complete([], 256)
    assert str(caught.value) == "provider_timeout_outcome_unknown"
    assert not caught.value.retryable


async def test_smoke_is_one_bounded_non_execution_probe(monkeypatch):
    remote_environment(monkeypatch, "qwen")
    calls = []

    def echo(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["max_tokens"] == 256
        return httpx.Response(200, json=valid_response(payload["messages"][-1]["content"]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(echo)) as client:
        remote = OpenAIProvider(client=client)
        no_consent = await smoke(confirm_paid_api=False, provider=remote)
        bad_budget = await smoke(confirm_paid_api=True, max_output_tokens=100000, provider=remote)
        assert (
            no_consent["provider_calls_attempted"]
            == bad_budget["provider_calls_attempted"]
            == len(calls)
            == 0
        )
        result = await smoke(confirm_paid_api=True, provider=remote)
    assert result["status"] == "passed" and len(calls) == 1
    assert result["evidence_type"] == "injected-transport-contract"
    assert result["is_model_benchmark"] is False
    assert result["limits"]["repository_bytes_sent"] == result["limits"]["tools_executed"] == 0
    assert result["usage"]["input_tokens"] == 100
    assert "never-used" not in json.dumps(result)


async def test_smoke_rejects_valid_json_that_does_not_follow_the_contract(monkeypatch):
    remote_environment(monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=valid_response()))
    ) as client:
        result = await smoke(confirm_paid_api=True, provider=OpenAIProvider(client=client))
    assert result["status"] == "failed" and result["checks"]["nonce_contract"] is False
    assert result["usage"] is not None


async def test_missing_smoke_configuration_makes_no_request(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Missing configuration must not construct an HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    result = await smoke(confirm_paid_api=True)
    assert result["status"] == "not_configured" and result["provider_calls_attempted"] == 0


def test_deepseek_server_variables_are_explicit_and_target_only_official_host(monkeypatch):
    monkeypatch.setenv("REPOPILOT_PROVIDER_FLAVOR", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-not-a-real-key")
    assert not configuration_check()["configured"]
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    config = RemoteConfig.from_environment()
    assert config.base_url == "https://api.deepseek.com"
    assert config.public_status()["thinking"] == "disabled"
    assert "not-a-real-key" not in json.dumps(config.public_status())
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.com/v1")
    assert not configuration_check()["configured"]


async def test_smoke_transient_failure_is_one_attempt_and_reports_unknown_usage(monkeypatch):
    remote_environment(monkeypatch, "deepseek")
    calls = []

    def reject(request):
        calls.append(request)
        return httpx.Response(429, text="private-provider-body")

    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
        report = await smoke(confirm_paid_api=True, provider=OpenAIProvider(client=client))
    assert len(calls) == report["provider_calls_attempted"] == 1
    assert report["status"] == "failed" and report["usage"] is None
    assert report["validated_responses"] == 0
    assert "private-provider-body" not in json.dumps(report)


async def test_provider_receipt_never_records_reasoning_or_secret_echo(monkeypatch):
    remote_environment(monkeypatch, "deepseek")
    body = valid_response()
    body["choices"][0]["message"]["reasoning_content"] = "private-chain-content"
    body["model"] = "test-key-never-used-on-network"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as client:
        reply = await OpenAIProvider(client=client).complete([], 256)
    serialized = reply.model_dump_json()
    assert "private-chain-content" not in serialized and "never-used-on-network" not in serialized
    assert "resolved_model" not in reply.provider_metadata
