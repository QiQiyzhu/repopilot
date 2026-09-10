import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  GitBranch,
  Layers,
  Square,
  Terminal,
  Waypoints,
  Database,
  FlaskConical,
  FileDiff,
  RefreshCw,
  ChevronRight,
} from "lucide-react";
import {
  api,
  terminal,
  seconds,
  type Task,
  type Health,
  type Memory,
  type Dashboard,
  type Evaluation,
} from "./api";
import {
  ContextPanel,
  EvaluationPanel,
  Json,
  MemoryPanel,
  OverviewPanel,
  VerificationPanel,
} from "./Panels";
import { TaskForm } from "./TaskForm";
const steps = [
  "UNDERSTAND",
  "PLAN",
  "EXECUTE",
  "VERIFY",
  "REPAIR",
  "FINISH",
  "FAILED",
];
const tabs = ["Trace", "Context", "Diff", "Verification"] as const;
type Section = "Tasks" | "Evaluation" | "Memory" | "Overview";
export default function App() {
  const [tasks, setTasks] = useState<Task[]>([]),
    [active, setActive] = useState<Task | null>(null),
    [health, setHealth] = useState<Health | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true),
    [tab, setTab] = useState<string>("Trace"),
    [section, setSection] = useState<Section>("Tasks"),
    [showForm, setShowForm] = useState(true),
    [memories, setMemories] = useState<Memory[]>([]),
    [dashboard, setDashboard] = useState<Dashboard | null>(null),
    [reports, setReports] = useState<Evaluation[]>([]);
  const handleError = useCallback(
    (e: unknown) => setError(e instanceof Error ? e.message : String(e)),
    [],
  );
  const reload = useCallback(async () => {
    try {
      const [rows, server] = await Promise.all([
        api<Task[]>("/tasks"),
        api<Health>("/health"),
      ]);
      setTasks(rows);
      setHealth(server);
    } catch (e) {
      handleError(e);
    } finally {
      setLoading(false);
    }
  }, [handleError]);
  useEffect(() => {
    void reload();
  }, [reload]);
  const activeId = active?.task_id,
    activeStatus = active?.status;
  useEffect(() => {
    if (!activeId || !activeStatus || terminal(activeStatus)) return;
    let mounted = true;
    const refresh = () => {
      void api<Task>("/tasks/" + activeId)
        .then((row) => {
          if (mounted) {
            setActive(row);
            if (terminal(row.status)) void reload();
          }
        })
        .catch(handleError);
    };
    const stream = new EventSource("/api/tasks/" + activeId + "/events");
    stream.addEventListener("trace", refresh);
    stream.addEventListener("done", refresh);
    const timer = setInterval(refresh, 1500);
    return () => {
      mounted = false;
      stream.close();
      clearInterval(timer);
    };
  }, [activeId, activeStatus, handleError, reload]);
  async function operation(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      handleError(e);
    } finally {
      setBusy(false);
    }
  }
  async function create(value: Record<string, unknown>) {
    await operation(async () => {
      const row = await api<Task>("/tasks", "POST", value);
      setActive(row);
      setShowForm(false);
      setTab("Trace");
      await reload();
    });
  }
  async function demo(transport: string) {
    if (!health) return;
    await create({
      repository: health.demo_repository,
      task: "Fix clamp so interior and both boundary cases pass",
      provider: "fake",
      transport,
      allow_repository_code: true,
    });
  }
  async function choose(row: Task) {
    await operation(async () => {
      setActive(await api<Task>("/tasks/" + row.task_id));
      setShowForm(false);
    });
  }
  async function navigate(name: Section) {
    setSection(name);
    setLoading(true);
    setError("");
    try {
      if (name === "Memory") setMemories(await api<Memory[]>("/memory"));
      else if (name === "Evaluation")
        setReports(await api<Evaluation[]>("/evaluations"));
      else if (name === "Overview")
        setDashboard(await api<Dashboard>("/dashboard"));
      else await reload();
    } catch (e) {
      handleError(e);
    } finally {
      setLoading(false);
    }
  }
  async function act(endpoint: string, body?: unknown) {
    if (!active) return;
    await operation(async () => {
      const response = await api<Task | unknown>(
        "/tasks/" + active.task_id + "/" + endpoint,
        "POST",
        body,
      );
      if (endpoint === "retry") {
        setActive(response as Task);
        setTab("Trace");
      } else setActive(await api<Task>("/tasks/" + active.task_id));
      await reload();
    });
  }
  const pending = active
    ? [...active.trace].reverse().find((e) => e.kind === "approval-required")
    : undefined;
  return (
    <div className="shell">
      <aside>
        <a className="brand" href="/">
          <span className="brandmark">
            <Waypoints size={24} />
          </span>
          RepoPilot<span className="version">LAB</span>
        </a>
        <div className="workspace">
          <GitBranch size={16} />
          <div>
            Local workspace<small>Agent engineering</small>
          </div>
        </div>
        <div className="nav-label">OBSERVATORY</div>
        {(["Tasks", "Evaluation", "Memory", "Overview"] as Section[]).map(
          (name) => {
            const Icon = {
              Tasks: Terminal,
              Evaluation: FlaskConical,
              Memory: Database,
              Overview: Activity,
            }[name];
            return (
              <button
                key={name}
                className={"nav " + (section === name ? "selected" : "")}
                onClick={() => void navigate(name)}
              >
                <Icon size={18} />
                {name}
                {section === name && <ChevronRight size={15} />}
              </button>
            );
          },
        )}
        <div className="aside-foot">
          <span className="dot" />{" "}
          {health ? "Backend connected" : "Backend unavailable"}
          <small>Evidence over self-assessment.</small>
        </div>
      </aside>
      <main>
        <header>
          <div>
            <span className="crumb">Workspace /</span> {section}
          </div>
          <button
            className="ghost"
            onClick={() => void navigate(section)}
            aria-label="Refresh current view"
          >
            <RefreshCw size={16} /> Refresh
          </button>
        </header>
        <div className="content">
          <div className="page-title">
            <div>
              <div className="eyebrow">REPOSITORY OPERATIONS</div>
              <h1>{section === "Tasks" ? "Task observatory" : section}</h1>
              <p>Follow the change from request to verified evidence.</p>
            </div>
            {section === "Tasks" && (
              <button className="primary" onClick={() => setShowForm(true)}>
                ＋ New task
              </button>
            )}
          </div>
          {error && (
            <div role="alert" className="alert">
              <strong>Request could not complete</strong>
              <p>{error}</p>
              <small>
                Service failures remain visible. Start the local backend on port
                8000 if it is unavailable.
              </small>
            </div>
          )}
          {loading && (
            <p className="loading" role="status">
              Loading recorded evidence…
            </p>
          )}
          {section === "Overview" && dashboard ? (
            <OverviewPanel value={dashboard} />
          ) : section === "Memory" ? (
            <MemoryPanel
              entries={memories}
              busy={busy}
              onInvalidate={(id) =>
                void operation(async () => {
                  await api("/memory/" + id + "/invalidate", "POST");
                  setMemories(await api<Memory[]>("/memory"));
                })
              }
            />
          ) : section === "Evaluation" ? (
            <EvaluationPanel reports={reports} />
          ) : section === "Tasks" ? (
            <>
              {showForm && (
                <TaskForm
                  health={health}
                  busy={busy}
                  onCreate={(value) => void create(value)}
                  onDemo={(transport) => void demo(transport)}
                  onError={setError}
                />
              )}
              <div className="workbench">
                <section className="panel task-list">
                  <div className="section-head">
                    <h2>Runs</h2>
                    <span className="chip">{tasks.length}</span>
                  </div>
                  {tasks.length === 0 ? (
                    <div className="empty">
                      <Layers size={28} />
                      <h3>No runs yet</h3>
                      <p>
                        Try the known fixture to collect the first actual
                        execution trace.
                      </p>
                    </div>
                  ) : (
                    tasks.map((row) => (
                      <button
                        className={
                          "run-row " +
                          (row.task_id === active?.task_id ? "active" : "")
                        }
                        key={row.task_id}
                        onClick={() => void choose(row)}
                      >
                        <span className={"status " + row.status}>
                          {row.status}
                        </span>
                        <strong>{row.task_id.slice(0, 12)}</strong>
                        <small>
                          {row.repository.split(/[\\/]/).at(-1)} ·{" "}
                          {row.step_count} steps
                        </small>
                      </button>
                    ))
                  )}
                </section>
                <section className="panel detail">
                  {!active ? (
                    <div className="empty big">
                      <Waypoints size={42} />
                      <h2>Every action leaves evidence.</h2>
                      <p>
                        Select a run to inspect its tools, retrieved context,
                        diff and verification results.
                      </p>
                      <div className="empty-flow">
                        Request <ChevronRight /> Tools <ChevronRight /> Verify{" "}
                        <ChevronRight /> Diff
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="section-head">
                        <div>
                          <span className={"status " + active.status}>
                            {active.status}
                          </span>
                          <h2>{active.task_id.slice(0, 12)}</h2>
                        </div>
                        {terminal(active.status) ? (
                          <button
                            disabled={busy}
                            onClick={() => void act("retry")}
                          >
                            <RefreshCw size={14} /> Retry task
                          </button>
                        ) : (
                          <button
                            disabled={busy}
                            onClick={() => void act("cancel")}
                          >
                            <Square size={14} /> Cancel task
                          </button>
                        )}
                      </div>
                      <p className="task-description">{active.request.task}</p>
                      {active.status === "awaiting_approval" && (
                        <div className="approval" role="alert">
                          <h3>Deletion needs your review</h3>
                          <p>
                            Requested file:{" "}
                            <code>
                              {String(pending?.input?.path ?? "See trace")}
                            </code>
                          </p>
                          <p>
                            The file is still present. No destructive operation
                            proceeds until you choose.
                          </p>
                          <div className="button-row">
                            <button
                              disabled={busy}
                              onClick={() =>
                                void act("approval", { approved: false })
                              }
                            >
                              Reject deletion
                            </button>
                            <button
                              className="danger"
                              disabled={busy}
                              onClick={() =>
                                void act("approval", { approved: true })
                              }
                            >
                              Approve deletion
                            </button>
                          </div>
                        </div>
                      )}
                      <div className="run-metrics">
                        <div>
                          <b>{active.step_count}</b>
                          <small>Steps</small>
                        </div>
                        <div>
                          <b>{seconds(active.latency_ms)}</b>
                          <small>Latency</small>
                        </div>
                        <div>
                          <b>
                            {active.usage.input_tokens +
                              active.usage.output_tokens}
                          </b>
                          <small>Reported tokens</small>
                        </div>
                        <div>
                          <b>{active.repair_count}</b>
                          <small>Repairs</small>
                        </div>
                      </div>
                      <div className="state-flow">
                        {steps.map((s) => (
                          <span
                            key={s}
                            className={active.state === s ? "current" : ""}
                          >
                            {s}
                          </span>
                        ))}
                      </div>
                      <div
                        className="tabs"
                        role="tablist"
                        aria-label="Run evidence"
                      >
                        {tabs.map((t) => (
                          <button
                            key={t}
                            role="tab"
                            aria-selected={tab === t}
                            onClick={() => setTab(t)}
                          >
                            {t === "Diff" && <FileDiff size={14} />} {t}
                          </button>
                        ))}
                      </div>
                      <p className="evidence">
                        {active.evidence_label} · {active.request.provider} ·{" "}
                        <code>{active.repository_commit.slice(0, 12)}</code> ·
                        cost{" "}
                        {active.usage.cost_usd == null
                          ? "not measured"
                          : "$" + active.usage.cost_usd.toFixed(6)}
                      </p>
                      {active.error && (
                        <p role="alert" className="alert">
                          {active.error}
                        </p>
                      )}
                      {tab === "Trace" ? (
                        <div className="timeline">
                          {active.trace.map((item, i) => (
                            <details
                              key={item.sequence || i}
                              className={
                                "trace-row " +
                                (item.result?.ok === false ? "trace-error" : "")
                              }
                            >
                              <summary>
                                <span className="step-index">
                                  {String(i + 1).padStart(2, "0")}
                                </span>
                                <div>
                                  <small>
                                    {item.state}{" "}
                                    {item.transport && " / " + item.transport}{" "}
                                    {item.tool && " / " + item.tool}
                                  </small>
                                  <strong>
                                    {item.kind === "verification"
                                      ? "Independent verification evidence recorded"
                                      : item.summary}
                                  </strong>
                                </div>
                                <time>{item.duration_ms.toFixed(1)} ms</time>
                              </summary>
                              <Json
                                value={
                                  item.kind === "verification"
                                    ? active.test_result
                                    : {
                                        input: item.input,
                                        result: item.result,
                                        usage: item.usage,
                                      }
                                }
                              />
                            </details>
                          ))}
                        </div>
                      ) : tab === "Context" ? (
                        <ContextPanel context={active.context} />
                      ) : tab === "Diff" ? (
                        <pre className="code diff">
                          {active.final_diff
                            ? active.final_diff.split("\n").map((line, i) => (
                                <span
                                  key={i}
                                  className={
                                    line.startsWith("+")
                                      ? "added"
                                      : line.startsWith("-")
                                        ? "removed"
                                        : ""
                                  }
                                >
                                  {line}
                                  {"\n"}
                                </span>
                              ))
                            : "No patch recorded."}
                        </pre>
                      ) : (
                        <VerificationPanel value={active.test_result} />
                      )}
                    </>
                  )}
                </section>
              </div>
            </>
          ) : null}
        </div>
      </main>
    </div>
  );
}
