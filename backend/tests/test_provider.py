import httpx
import pytest
from repopilot.providers import OpenAIProvider, ProviderError


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
