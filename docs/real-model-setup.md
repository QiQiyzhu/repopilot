# DeepSeek: explicit, bounded real-model access

For the frozen six-task, two-condition comparison with Docker-isolated execution and controller-only API credentials, follow [the capsule evaluation protocol](capsule-evaluation.md). It is a separate manual, paid opt-in workflow; the normal app and the historical single-task smoke below retain their original scope.

RepoPilot uses the same structured `Action` contract for remote models, Fake and Replay. The documented cloud setup is **DeepSeek**. The existing run selector is still named `openai` for compatibility with saved requests; it selects the HTTP adapter, while `REPOPILOT_PROVIDER_FLAVOR=deepseek` selects DeepSeek's endpoint and payload. It does not send a DeepSeek request to OpenAI.

The default demo and CI use no cloud credentials. A configured provider does not start requests automatically. Neither a connectivity check nor a nonce response measures coding ability; the 36-task, five-profile real-model ablation remains a separate experiment.

## Server configuration

Use a local server process environment, never a browser variable, prompt, Git file or screenshot. The application does **not** automatically load a `.env` file. `.env.example` documents the settings; Docker's default demo does not forward API keys.

```powershell
$env:REPOPILOT_PROVIDER_FLAVOR = 'deepseek'
$env:DEEPSEEK_MODEL = 'deepseek-flash'
$env:DEEPSEEK_BASE_URL = 'https://api.deepseek.com'
$env:REPOPILOT_PROVIDER_TIMEOUT_SECONDS = '45'
$dsSecret = Read-Host 'DeepSeek API key (hidden)' -AsSecureString
$dsPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($dsSecret)
try {
  $env:DEEPSEEK_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($dsPointer)
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($dsPointer)
  Remove-Variable dsSecret, dsPointer
}
```

This places the value only in the current process environment and child server processes. Remove it with `Remove-Item Env:DEEPSEEK_API_KEY` when finished. A key already disclosed in a conversation should be replaced in the provider console before reuse. No key value belongs in the examples or evidence.

As checked on 2026-09-10, the [official first-call page](https://api-docs.deepseek.com/) recommends `deepseek-flash` and accepts the legacy `deepseek-v4-flash` name. Alias routing may change; retain both requested and resolved model names in each receipt. This project makes no fixed-price assumption. Check the provider console before a larger experiment.

## First check: zero requests

From the repository root, using the installed virtual environment:

```powershell
.venv/Scripts/python.exe -m repopilot.cli provider-check
```

This validates configuration locally. It prints `network_checked: false`, model/flavor and a sanitized base URL, never the key. It rejects missing model/key, malformed or credential-bearing URLs, unresolved placeholders, non-finite timeouts and incomplete price settings. DeepSeek flavor permits only `https://api.deepseek.com` or its `/v1` form; use a deliberately configured `compatible` flavor for another trusted endpoint.

## One real response: bounded probe

```powershell
.venv/Scripts/python.exe -m repopilot.cli provider-smoke --execute --max-output-tokens 256 --output outputs/deepseek-smoke.json
```

Without `--execute` the command performs **zero** model calls. `--confirm-paid-api` remains an equivalent flag. The probe sends a fresh nonce in a tiny JSON Action example and checks the returned action schema and exact nonce. It never reads repository context or runs an action returned by the model.

| Bound | Actual behavior |
|---|---|
| Requests | At most 1; no retries, including HTTP 429 |
| Output | Default 256 tokens; CLI rejects values outside 64–512 |
| Time | Default 45 seconds; configured upper bound 120 seconds |
| Repository / tools | 0 repository bytes sent; 0 tools executed |
| Stored data | Timestamp, normalized source hashes, Git receipt, model/request identifiers, measured latency, provider-reported usage and boolean checks |
| Not stored | Key, raw provider error body, arbitrary response text or reasoning content |
| Unknown cost | `null`; a failed/timeout request may still be billed |

The DeepSeek payload uses `max_tokens`, `response_format: {"type":"json_object"}`, and `thinking: {"type":"disabled"}`. It does **not** send Qwen's `enable_thinking` flag. The prompt includes a JSON example, and local Pydantic validation still enforces the Action schema. Empty, refused, truncated or malformed replies fail; none becomes a Fake result. See [official JSON output](https://api-docs.deepseek.com/guides/json_mode/) and [thinking mode](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/).

## Running a repository task

For a single trusted authored fixture, a bounded end-to-end runner is available:

```powershell
.venv/Scripts/python.exe -m repopilot.provider_task --execute --data D:/CodexData/RepoPilot/deepseek-fixture --output outputs/deepseek-task.json
```

It creates a fresh clamp fixture and lets the configured model choose the actions and modification. At most six provider attempts are permitted, retries are disabled, output is capped at 4000 tokens per call, the observed total-token budget is 16000 and the whole harness budget is 180 seconds. Final acceptance reruns the three authored pytest cases and independently requires the original tests to remain unchanged and only `calculator.py` to change. No reference patch is sent. The JSON retains the actual task, diff, trace, acceptance, usage and source hashes, including failures. This single visible-test fixture is an integration experiment, not a representative code benchmark.

The first [actual DeepSeek nonce probe](evidence/deepseek-smoke.json) passed on 2026-09-10: **1 response, 107 input tokens, 47 output tokens, 1047 ms**. It ran against an uncommitted integration tree and records normalized source-file hashes; those hashes were checked against the delivered implementation. Cost is `null` because no account-specific price rates were supplied. This recorded result says nothing about code correctness or latency percentiles.

The subsequent [actual authored-fixture run](evidence/deepseek-task.json) was accepted after **4 model calls**. The model chose `run_tests` (three failures), `apply_patch`, `run_tests` (three passes), then `finish`. The verifier independently reran the three tests and checked the diff. The model generated `min(high, max(low, value))`; no reference patch was supplied. The original tests remained unchanged and only `calculator.py` changed. Observed usage was **10,277 input / 323 output tokens**, with **5.437 seconds** of harness latency. Source-file hashes match the implementation at execution; the public receipt replaces specific local paths and retains the original receipt hash. One visible-test fixture cannot estimate a general success rate or an ablation effect.

Only run code that you trust. The existing application permits the `openai` provider in a task request. That selector now uses the configured DeepSeek flavor. Start the backend from the environment above:

```powershell
.venv/Scripts/python.exe -m repopilot.cli serve
```

For an API-submitted task, set an explicit budget, for example `max_steps: 8`, `max_tokens: 6000`, `timeout_seconds: 180`, `max_repairs: 1`, `provider_retries: 0`. These are proposed pilot limits, not evidence of a completed task. An output cap cannot bound prompt tokens or guarantee a prepaid cost ceiling. The harness records real usage and stops on observed budget exhaustion. USD estimates require both operator-supplied input and output rates; a configured cost budget without rates is rejected.

The same integration is available through **New task → Model provider → DeepSeek（服务端配置）**. `/health` returns only configuration status, flavor and model; it never returns the key or credential-bearing URLs and makes no model request. An unconfigured DeepSeek selection keeps **Run task** disabled. Once the server configuration is present, the form posts the real `openai` adapter selector with explicit limits: six steps/calls, zero retries or repairs, 16,000 total tokens, 1,800 context tokens and 180 seconds. These UI limits can be lowered in the advanced section. The form has no credential input. Its state is configuration readiness, not a cloud connection test; an expired key still fails visibly at execution. The existing demo buttons always execute the labelled zero-cloud-call fixture.

The additional browser contract check supplies a controlled readiness response, intercepts the actual submission before it reaches the backend, and asserts the selected remote provider and the edited bounded budget. It records **no real model run**. The six other browser workflows use the actual local backend, including a direct API request that verifies missing credentials still fail closed even if the UI is bypassed.

The larger runner in [run_model_benchmark.py](../scripts/run_model_benchmark.py) supports the same DeepSeek variables. Start with one named task and one profile and inspect its acceptance, trace and usage before extending it. Its broad defaults are an experiment runner, not the connectivity probe. Do not run all 180 task/profile combinations just to prove an API key works.

## What the failure controls prove

[Provider tests](../backend/tests/test_provider.py) use injected HTTP transports, not billable model requests. They cover vendor-specific payloads, malformed URLs, missing credentials, refusal/empty/truncated content, invalid or missing usage, 401/429/503, timeout outcomes, nonce mismatch, one-call probe bounds and receipt redaction. [Harness tests](../backend/tests/test_harness.py) prove permanent errors stop immediately; retryable statuses remain bounded by the task budget. Read timeouts are not retried because billing outcome is unknown.

This is **integration and contract evidence**. A passed smoke establishes that one service response met a narrow contract. Code quality still depends on independent executable acceptance; see the [93-green-tests counterexample](decision-case-study.md). Claims about model success rate, ablation improvement, production reliability or user benefit require their own recorded experiments.
