export interface Usage {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
}
export interface ToolResult {
  ok: boolean;
  output: string;
  error?: string | null;
  exit_code?: number | null;
  requires_approval?: boolean;
  truncated?: boolean;
}
export interface Trace {
  sequence: number;
  state: string;
  kind: string;
  summary: string;
  tool?: string;
  transport?: string;
  duration_ms: number;
  timestamp: string;
  result?: ToolResult | null;
  input?: Record<string, unknown> | null;
  usage?: Usage | null;
}
export interface ContextChunk {
  source: string;
  path: string;
  start_line: number;
  content: string;
  tokens: number;
  provenance?: unknown;
}
export interface Context {
  strategy?: string;
  context_tokens?: number;
  budget?: number;
  retrieved_files?: string[];
  retrieved_chunks?: ContextChunk[];
  discarded_context?: Array<{
    path: string;
    start_line: number;
    reason: string;
    tokens: number;
  }>;
}
export interface VerificationCheck extends Partial<ToolResult> {
  name: string;
  layer: string;
}
export interface Verification {
  passed: boolean;
  checks: VerificationCheck[];
  changed_files: string[];
  evidence_source: string;
  model_judge: boolean;
}
export interface Task {
  task_id: string;
  status: string;
  state: string;
  created_at: string;
  repository: string;
  workspace: string | null;
  repository_commit: string;
  step_count: number;
  repair_count: number;
  trace: Trace[];
  context: Context;
  final_diff: string;
  test_result: Verification | null;
  error: string | null;
  evidence_label: string;
  latency_ms: number;
  request: {
    provider: string;
    task: string;
    transport: string;
    skill: string | null;
  };
  usage: Usage;
}
export interface Health {
  status: string;
  version: string;
  demo_repository: string;
  real_provider_configured: boolean;
  repository_root: string;
}
export interface Memory {
  id: string;
  kind: string;
  repository: string;
  commit: string;
  content: string;
  task_id: string;
  provenance: unknown[];
  trusted: boolean;
  valid: boolean;
}
export interface Dashboard {
  task_count: number;
  completed_count: number;
  success_rate: number | null;
  average_steps: number | null;
  average_latency_ms: number | null;
  tool_error_rate: number | null;
  test_pass_rate: number | null;
  token_usage: number;
  repair_count: number;
  provider_counts: Record<string, number>;
  note: string;
}
export interface EvaluationRow {
  task_id?: string;
  category?: string;
  validated?: boolean;
  profile?: string;
  label?: string;
  sample_count?: number;
  independent_acceptance_passed?: boolean;
  steps?: number;
  latency_ms?: number;
  memory_chunks?: number;
  tool_errors?: number;
  repair_attempts?: number;
  status?: string;
  success_rate?: number | null;
}
export interface Evaluation {
  id: string;
  title?: string;
  evidence_type?: string;
  is_model_benchmark: boolean;
  repository_commit?: string;
  task_count?: number;
  validated_count?: number;
  real_model_runs?: number;
  note?: string;
  conclusion?: string;
  rows?: EvaluationRow[];
  model_ablation?: EvaluationRow[];
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const options: RequestInit = { method };
  if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  const response = await fetch("/api" + path, options);
  if (!response.ok) {
    let message = "HTTP " + response.status;
    try {
      const detail = (await response.json()).detail;
      message = typeof detail === "string" ? detail : JSON.stringify(detail);
    } catch {
      /* Non-JSON proxy error. */
    }
    throw Error(message.slice(0, 700));
  }
  return response.json();
}
export const terminal = (status: string) =>
  ["succeeded", "failed", "cancelled", "timed_out", "unverified"].includes(
    status,
  );
export const percent = (value: number | null | undefined) =>
  value == null ? "—" : (value * 100).toFixed(1) + "%";
export const seconds = (value: number | null | undefined) =>
  value == null ? "—" : (value / 1000).toFixed(2) + "s";
