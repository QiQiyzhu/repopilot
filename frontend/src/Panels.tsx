import { CheckCircle2, XCircle, Database, Layers } from "lucide-react";
import {
  percent,
  seconds,
  type Context,
  type Dashboard,
  type Evaluation,
  type Memory,
  type Verification,
} from "./api";
export function Json({ value }: { value: unknown }) {
  return <pre className="code">{JSON.stringify(value, null, 2)}</pre>;
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="empty">
      <Layers size={30} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function ContextPanel({ context }: { context: Context }) {
  const chunks = context.retrieved_chunks ?? [];
  return (
    <div>
      <div className="context-summary">
        <b>
          {context.context_tokens ?? 0} / {context.budget ?? "—"} tokens
        </b>
        <span>
          {context.strategy ?? "Not retrieved"} ·{" "}
          {context.retrieved_files?.length ?? 0} files · {chunks.length} chunks
        </span>
      </div>
      <p>
        Conservative local estimate; provider-reported usage is recorded
        separately.
      </p>
      {chunks.length === 0 ? (
        <Empty title="No context selected">
          This configuration may have context retrieval disabled.
        </Empty>
      ) : (
        chunks.map((chunk, i) => (
          <details className="context-card" key={i}>
            <summary>
              <span className="chip">{chunk.source}</span>
              <strong>
                {chunk.path}:{chunk.start_line}
              </strong>
              <small>{chunk.tokens} tokens</small>
            </summary>
            <pre className="code">{chunk.content}</pre>
            {chunk.provenance != null && <Json value={chunk.provenance} />}
          </details>
        ))
      )}
      <details className="context-card">
        <summary>
          Discarded context · {context.discarded_context?.length ?? 0} chunks
        </summary>
        <Json value={context.discarded_context ?? []} />
      </details>
    </div>
  );
}
export function VerificationPanel({ value }: { value: Verification | null }) {
  if (!value)
    return (
      <Empty title="No verification result">
        Unverified runs need an independent evaluator. A model saying “done”
        does not count as evidence.
      </Empty>
    );
  return (
    <div>
      <div
        className={
          "verification-banner " + (value.passed ? "passed" : "rejected")
        }
      >
        {value.passed ? <CheckCircle2 size={22} /> : <XCircle size={22} />}
        <div>
          <strong>
            {value.passed
              ? "Executable checks passed"
              : "Verifier rejected this result"}
          </strong>
          <small>
            {value.checks.filter((x) => x.ok).length} / {value.checks.length}{" "}
            checks · no model judge
          </small>
        </div>
      </div>
      {value.checks.map((check, i) => (
        <details className="check-row" key={i}>
          <summary>
            {check.ok ? (
              <CheckCircle2 size={16} color="#238454" />
            ) : (
              <XCircle size={16} color="#b24e43" />
            )}
            <strong>{check.name}</strong>
            <span>{check.layer}</span>
            <small>
              {check.exit_code != null ? "exit " + check.exit_code : ""}
            </small>
          </summary>
          {(check.output || check.error) && (
            <pre className="code">{check.output || check.error}</pre>
          )}
        </details>
      ))}
      <p>Changed files: {value.changed_files.join(", ") || "none"}</p>
    </div>
  );
}
export function OverviewPanel({ value }: { value: Dashboard }) {
  const metrics = [
    ["Recorded tasks", value.task_count],
    ["Verified success", percent(value.success_rate)],
    ["Average steps", value.average_steps?.toFixed(1) ?? "—"],
    ["Average latency", seconds(value.average_latency_ms)],
    ["Tool error rate", percent(value.tool_error_rate)],
    ["Test pass rate", percent(value.test_pass_rate)],
    ["Reported tokens", value.token_usage],
    ["Repair attempts", value.repair_count],
  ];
  return (
    <>
      <div className="metric-grid">
        {metrics.map(([label, v]) => (
          <div className="panel metric" key={label}>
            <span>{label}</span>
            <strong>{v}</strong>
          </div>
        ))}
      </div>
      <section className="panel">
        <h2>Know what the numbers measure</h2>
        <p>{value.note}</p>
        <div className="provider-breakdown">
          {Object.entries(value.provider_counts).map(([name, count]) => (
            <div key={name}>
              <b>{count}</b>
              <span>
                {name === "fake"
                  ? "Deterministic fixture"
                  : name === "replay"
                    ? "Recorded actions"
                    : "Real provider"}
              </span>
            </div>
          ))}
        </div>
        <p>
          Failed reproduction tests are expected tool errors in the
          demonstration. Unknown rates stay blank; zero fake tokens mean no
          model call.
        </p>
      </section>
    </>
  );
}
export function MemoryPanel({
  entries,
  onInvalidate,
  busy,
}: {
  entries: Memory[];
  onInvalidate: (id: string) => void;
  busy: boolean;
}) {
  return (
    <section className="panel">
      <h2>Scoped lessons and provenance</h2>
      <p>
        Only verified evidence is retrieved. Entries require the exact
        repository path and commit; invalidation removes an entry from future
        retrieval.
      </p>
      {entries.length === 0 ? (
        <Empty title="No verified memories">
          Complete a task with memory enabled to record its checked evidence.
        </Empty>
      ) : (
        <div className="memory-grid">
          {entries.map((entry) => (
            <article
              className={"memory-card " + (!entry.valid ? "invalid" : "")}
              key={entry.id}
            >
              <div className="section-head">
                <span className="chip">
                  <Database size={12} /> {entry.kind}
                </span>
                <span className="status">
                  {!entry.valid
                    ? "invalidated"
                    : entry.trusted
                      ? "verified"
                      : "untrusted"}
                </span>
              </div>
              <p>{entry.content}</p>
              <small>
                {entry.repository.split(/[\\/]/).at(-1)} ·{" "}
                {entry.commit.slice(0, 12)}
              </small>
              <details>
                <summary>Evidence provenance</summary>
                <Json value={entry.provenance} />
              </details>
              <button
                disabled={busy || !entry.valid}
                onClick={() => onInvalidate(entry.id)}
              >
                {entry.valid ? "Invalidate memory" : "Invalidated"}
              </button>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
export function EvaluationPanel({ reports }: { reports: Evaluation[] }) {
  return (
    <>
      <section className="panel evidence-note">
        <span className="chip">MEASUREMENT BOUNDARY</span>
        <h2>Validated tasks. Unmeasured model performance.</h2>
        <p>
          Reference repairs and deterministic scripts validate the platform.
          They do not establish that an LLM can solve the benchmark.
          Real-provider ablations remain “not run” until explicitly executed.
        </p>
      </section>
      {reports.length === 0 ? (
        <section className="panel">
          <Empty title="No evaluation reports">
            Run the documented local evaluation commands to create evidence.
          </Empty>
        </section>
      ) : (
        reports.map((report) => (
          <section className="panel report" key={report.id}>
            <div className="section-head">
              <div>
                <h2>{report.title ?? report.id}</h2>
                <small>{report.evidence_type ?? "Recorded evidence"}</small>
              </div>
              <span className="chip">
                {report.is_model_benchmark
                  ? "Real-model experiment"
                  : "Harness / contract validation"}
              </span>
            </div>
            {report.task_count != null && (
              <div className="report-count">
                <b>
                  {report.validated_count} / {report.task_count}
                </b>
                <span>task contracts validated</span>
              </div>
            )}
            <p>{report.note ?? report.conclusion}</p>
            {report.repository_commit && (
              <p>
                ARC//SHIFT baseline{" "}
                <code>{report.repository_commit.slice(0, 12)}</code>
              </p>
            )}
            {report.id === "arc-contract-validation" ? (
              <details>
                <summary>
                  Inspect all {report.rows?.length} independent task contracts
                </summary>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Task</th>
                        <th>Category</th>
                        <th>Controls</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.rows?.map((row) => (
                        <tr key={row.task_id}>
                          <td>{row.task_id}</td>
                          <td>{row.category}</td>
                          <td>
                            {row.validated
                              ? "Positive + negative passed"
                              : "Needs review"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            ) : report.id === "harness-ablation" ? (
              <>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Configuration</th>
                        <th>Acceptance</th>
                        <th>Steps</th>
                        <th>Latency</th>
                        <th>Memory</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.rows?.map((row) => (
                        <tr key={row.profile}>
                          <td>{row.label}</td>
                          <td>
                            {row.independent_acceptance_passed
                              ? "Passed"
                              : "Failed"}
                          </td>
                          <td>{row.steps}</td>
                          <td>{seconds(row.latency_ms)}</td>
                          <td>{row.memory_chunks} chunks</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="unrun">
                  <b>Real-model ablation</b>
                  {report.model_ablation?.map((row) => (
                    <span key={row.profile}>
                      {row.profile} <em>not run</em>
                    </span>
                  ))}
                </div>
                <p>
                  One scripted sample per configuration. Latency is overhead
                  observation, not a statistically meaningful model comparison.
                </p>
              </>
            ) : (
              <details>
                <summary>View evidence record</summary>
                <Json value={report} />
              </details>
            )}
          </section>
        ))
      )}
    </>
  );
}
