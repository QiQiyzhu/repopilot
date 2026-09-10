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
    [acceptance, setAcceptance] = useState("");
  function submit(event: React.FormEvent) {
    event.preventDefault();
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
              onChange={(e) => setProvider(e.target.value)}
            >
              <option value="fake">
                Deterministic fake · included fixture only
              </option>
              <option value="openai">Configured real provider</option>
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
        {provider === "openai" && !health?.real_provider_configured && (
          <p className="inline-warning">
            A real provider is not configured. Set OPENAI_API_KEY and
            OPENAI_MODEL in the backend environment; a request will fail
            explicitly until then.
          </p>
        )}
        <details className="advanced">
          <summary>Budget and executable acceptance criteria</summary>
          <div className="form-grid">
            <label>
              Maximum steps
              <input
                type="number"
                min={1}
                max={100}
                value={maxSteps}
                onChange={(e) => setMaxSteps(Number(e.target.value))}
              />
            </label>
            <label>
              Timeout (seconds)
              <input
                type="number"
                min={1}
                max={1800}
                value={timeout}
                onChange={(e) => setTimeout(Number(e.target.value))}
              />
            </label>
            <label>
              Repair attempts
              <input
                type="number"
                min={0}
                max={5}
                value={repairs}
                onChange={(e) => setRepairs(Number(e.target.value))}
              />
            </label>
            <label>
              Context tokens
              <input
                type="number"
                min={64}
                max={32000}
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
            disabled={busy || !repository.trim() || task.trim().length < 3}
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
