import { useState } from "react";
import { Play } from "lucide-react";
import type { Health } from "./api";
export function TaskForm({
  health,
  busy,
  onCreate,
  onDemo,
  onError,
}: {
  health: Health | null;
  busy: boolean;
  onCreate: (value: Record<string, unknown>) => void;
  onDemo: (transport: string) => void;
  onError: (message: string) => void;
}) {
  const [repository, setRepository] = useState(""),
    [task, setTask] = useState(""),
    [provider, setProvider] = useState("fake"),
    [transport, setTransport] = useState("native"),
    [skill, setSkill] = useState("bug-fix"),
    [strategy, setStrategy] = useState("structured"),
    [memory, setMemory] = useState(true),
    [trusted, setTrusted] = useState(false),
    [replay, setReplay] = useState(""),
    [maxSteps, setMaxSteps] = useState(24),
    [timeout, setTimeout] = useState(120),
    [repairs, setRepairs] = useState(2),
    [tokens, setTokens] = useState(6000),
    [totalTokens, setTotalTokens] = useState(40000),
    [acceptance, setAcceptance] = useState("");
  const remoteReady =
    health?.real_provider_configured &&
    health.real_provider?.flavor === "deepseek";
  const remoteBlocked = provider === "openai" && !remoteReady;
  function selectProvider(value: string) {
    setProvider(value);
    setMaxSteps(value === "openai" ? 6 : 24);
    setTimeout(value === "openai" ? 180 : 120);
    setRepairs(value === "openai" ? 0 : 2);
    setTokens(value === "openai" ? 1800 : 6000);
    setTotalTokens(value === "openai" ? 16000 : 40000);
  }
  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (remoteBlocked) {
      onError("DeepSeek is not configured in the backend environment.");
      return;
    }
    try {
      const criteria = acceptance.trim()
        ? JSON.parse(acceptance)
        : { require_diff: skill !== "code-review" };
      onCreate({
        repository,
        task,
        provider,
        transport,
        skill: skill || null,
        context_strategy: strategy,
        memory_enabled: memory,
        allow_repository_code: trusted,
        replay_id: replay || null,
        budget: {
          max_steps: maxSteps,
          timeout_seconds: timeout,
          max_repairs: repairs,
          context_tokens: tokens,
          max_tokens: totalTokens,
          provider_retries: provider === "openai" ? 0 : 2,
        },
        acceptance: criteria,
      });
    } catch {
      onError("Acceptance criteria must be valid JSON.");
    }
  }
  return (
    <section className="panel task-form">
      <div className="section-head">
        <h2>Create an isolated task</h2>
        <span className="chip">Committed source stays intact</span>
      </div>
      <div className="demo-banner">
        <div>
          <b>See a real execution in 5 seconds</b>
          <p>
            A deterministic script repairs the included clamp fixture, runs
            pytest, and records its actual diff. No API key needed.
          </p>
        </div>
        <div className="button-row">
          <button disabled={busy || !health} onClick={() => onDemo("native")}>
            <Play size={14} /> Run native demo
          </button>
          <button
            className="primary"
            disabled={busy || !health}
            onClick={() => onDemo("mcp")}
          >
            <Play size={14} /> Run MCP demo
          </button>
        </div>
      </div>
      <form onSubmit={submit}>
        <label>
          Git repository path
          <input
            required
            value={repository}
            onChange={(e) => setRepository(e.target.value)}
            placeholder={
              health?.demo_repository ??
              "Absolute path to a trusted local Git repository"
            }
          />
        </label>
        <label>
          What should change?
          <textarea
            required
            minLength={3}
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="Describe a bounded task and the behavior you expect."
            rows={3}
          />
        </label>
        <div className="form-grid">
          <label>
            Model provider
            <select
              value={provider}
              onChange={(e) => selectProvider(e.target.value)}
            >
              <option value="fake">
                演示（零云端调用）· included fixture only
              </option>
              <option value="openai">DeepSeek（服务端配置）</option>
              <option value="replay">Replay previous actions</option>
            </select>
          </label>
          <label>
            Tool transport
            <select
              value={transport}
              onChange={(e) => setTransport(e.target.value)}
            >
              <option>native</option>
              <option>mcp</option>
            </select>
          </label>
          <label>
            Skill
            <select value={skill} onChange={(e) => setSkill(e.target.value)}>
              <option value="">No skill</option>
              {[
                "bug-fix",
                "add-unit-test",
                "frontend-change",
                "performance-investigation",
                "code-review",
              ].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
          <label>
            Context strategy
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
            >
              <option>structured</option>
              <option>naive</option>
            </select>
          </label>
        </div>
        {provider === "replay" && (
          <label>
            Replay task ID
            <input
              required
              value={replay}
              onChange={(e) => setReplay(e.target.value)}
              placeholder="The UUID of a previously completed local task"
            />
          </label>
        )}
        {provider === "openai" && (
          <div
            className={remoteReady ? "provider-readiness" : "inline-warning"}
            role="status"
          >
            {remoteReady ? (
              <>
                <strong>
                  DeepSeek configured · {health?.real_provider?.model}
                </strong>
                <p>
                  服务端密钥已配置。提交任务才会调用云端；最多 6 次模型调用、0
                  次重试、16,000 个总 tokens、180
                  秒。下方预算可以进一步降低。观测到用量后停止，不是预付费额度锁。
                </p>
              </>
            ) : (
              <>
                <strong>DeepSeek is not configured.</strong>
                <p>
                  Set DEEPSEEK_API_KEY, DEEPSEEK_MODEL and
                  REPOPILOT_PROVIDER_FLAVOR=deepseek in the backend environment,
                  then start the server from that environment and refresh this
                  page. Keys are never entered in this browser.
                </p>
              </>
            )}
          </div>
        )}
        <details className="advanced">
          <summary>Budget and executable acceptance criteria</summary>
          <div className="form-grid">
            <label>
              Maximum steps
              <input
                type="number"
                min={1}
                max={provider === "openai" ? 6 : 100}
                value={maxSteps}
                onChange={(e) => setMaxSteps(Number(e.target.value))}
              />
            </label>
            <label>
              Timeout (seconds)
              <input
                type="number"
                min={1}
                max={provider === "openai" ? 180 : 1800}
                value={timeout}
                onChange={(e) => setTimeout(Number(e.target.value))}
              />
            </label>
            <label>
              Repair attempts
              <input
                type="number"
                min={0}
                max={provider === "openai" ? 0 : 5}
                value={repairs}
                onChange={(e) => setRepairs(Number(e.target.value))}
              />
            </label>
            <label>
              Total token budget
              <input
                type="number"
                min={64}
                max={provider === "openai" ? 16000 : 1000000}
                value={totalTokens}
                onChange={(e) => setTotalTokens(Number(e.target.value))}
              />
            </label>
            <label>
              Context tokens
              <input
                type="number"
                min={64}
                max={provider === "openai" ? 1800 : 32000}
                value={tokens}
                onChange={(e) => setTokens(Number(e.target.value))}
              />
            </label>
          </div>
          <label>
            Acceptance JSON
            <textarea
              rows={5}
              value={acceptance}
              onChange={(e) => setAcceptance(e.target.value)}
              placeholder={
                '{"checks":[{"name":"unit","command":["python","-m","pytest","-q"],"layer":"unit"}],"expected_files":["calculator.py"]}'
              }
            />
          </label>
          <p>
            Empty criteria rerun the most recently executed tests. Reviews
            require no changes; other tasks require a diff.
          </p>
        </details>
        <div className="form-foot">
          <div>
            <label className="check">
              <input
                type="checkbox"
                checked={memory}
                onChange={(e) => setMemory(e.target.checked)}
              />{" "}
              Retrieve verified memory
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={trusted}
                onChange={(e) => setTrusted(e.target.checked)}
              />{" "}
              I trust this repository’s test code to run locally
            </label>
          </div>
          <button
            className="primary"
            type="submit"
            disabled={
              busy ||
              !health ||
              remoteBlocked ||
              !repository.trim() ||
              task.trim().length < 3
            }
          >
            <Play size={16} />
            {busy ? "Creating workspace…" : "Run task"}
          </button>
        </div>
        <small>
          Path and command restrictions are defense in depth, not an
          operating-system sandbox. The demo buttons run only the included,
          known fixture.
        </small>
      </form>
    </section>
  );
}
