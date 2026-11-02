export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const PASSWORD_KEY = "agentdesk:password";

export function getStoredPassword(): string {
  try {
    return sessionStorage.getItem(PASSWORD_KEY) ?? "";
  } catch {
    return "";
  }
}

export function storePassword(password: string) {
  try {
    sessionStorage.setItem(PASSWORD_KEY, password);
  } catch {
    // sessionStorage unavailable (private mode etc.) — fall through, the
    // in-memory copy held by the caller for this session still works.
  }
}

export function clearStoredPassword() {
  try {
    sessionStorage.removeItem(PASSWORD_KEY);
  } catch {
    /* noop */
  }
}

function authHeaders(password: string): HeadersInit {
  return password ? { "X-App-Password": password } : {};
}

export async function checkPassword(password: string): Promise<boolean> {
  const res = await fetch(`${API_BASE}/api/auth/check`, {
    method: "POST",
    headers: authHeaders(password),
  });
  return res.ok;
}

export interface Health {
  status: string;
  model: string;
}

/** Unauthenticated liveness probe; also tells us which model is serving. */
export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const res = await fetch(`${API_BASE}/health`, { signal });
  if (!res.ok) throw new ApiError(`Health check failed (${res.status}).`, res.status);
  return res.json();
}

export interface TraceEntry {
  node: string;
  detail: string;
  elapsed_ms: number;
}

export interface Citation {
  source_id: string;
  type: "rag" | "web" | string;
  file?: string;
  chunk_index?: number;
  score?: number;
  url?: string;
  title?: string;
}

export type Depth = "quick" | "deep";

export interface ReportResult {
  run_id?: string | null;
  question: string;
  depth?: Depth | null;
  status: string;
  report: string;
  citations: Citation[];
  revisions: number;
  research_rounds: number;
  critic: {
    verdict: string | null;
    feedback: string | null;
    unsupported_claims: string[];
  };
  trace: TraceEntry[];
}

export class ApiError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
  }
}

/** The Planner's plan, paused for a human to approve or edit before research. */
export interface PlanReview {
  run_id: string;
  question?: string;
  question_type?: string | null;
  subtasks: string[];
  success_criteria: string[];
  use_rag: boolean;
  use_web: boolean;
}

export type PlanEdits = Partial<Pick<PlanReview, "subtasks" | "success_criteria" | "use_rag" | "use_web">>;

export interface StreamHandlers {
  onRun?: (runId: string) => void;
  onProgress: (entry: TraceEntry) => void;
  onReport: (result: ReportResult) => void;
  onPlanReview?: (plan: PlanReview) => void;
  onCancelled?: () => void;
  onError: (message: string) => void;
}

export interface StreamOptions {
  depth?: Depth;
  /** Pause after the Planner so a human can approve or edit the plan. */
  reviewPlan?: boolean;
}

/** Parses a `text/event-stream` body read via fetch (EventSource can't do POST). */
export async function streamReport(
  question: string,
  password: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
  options: StreamOptions = {},
): Promise<void> {
  const body: Record<string, unknown> = { question };
  if (options.depth) body.depth = options.depth;
  if (options.reviewPlan) body.review_plan = true;
  await postStream(`${API_BASE}/api/report/stream`, body, password, handlers, signal);
}

/** Approve (optionally edited) a paused plan, or continue a failed run; streams the rest. */
export async function resumeRun(
  runId: string,
  password: string,
  edits: PlanEdits,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  await postStream(`${API_BASE}/api/runs/${encodeURIComponent(runId)}/resume`, { action: "approve", ...edits }, password, handlers, signal);
}

export async function rejectRun(runId: string, password: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(runId)}/resume`, {
    method: "POST",
    headers: { "content-type": "application/json", ...authHeaders(password) },
    body: JSON.stringify({ action: "reject" }),
  });
  if (!res.ok) throw new ApiError(await errorDetail(res), res.status);
}

/** Ask the server to stop a run; an executing one halts at its next node boundary. */
export async function cancelRun(runId: string, password: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
    headers: authHeaders(password),
  });
  if (!res.ok && res.status !== 409) throw new ApiError(await errorDetail(res), res.status);
}

export interface ServerRun {
  run_id: string;
  question: string;
  status: "running" | "awaiting_review" | "completed" | "failed" | "cancelled";
  error: string | null;
  trace: TraceEntry[];
  pending_review: Omit<PlanReview, "run_id"> | null;
  result: ReportResult | null;
}

/** A run as the server remembers it: survives page reloads and dropped connections. */
export async function fetchRun(runId: string, password: string, signal?: AbortSignal): Promise<ServerRun> {
  const res = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(runId)}`, { headers: authHeaders(password), signal });
  if (!res.ok) throw new ApiError(await errorDetail(res), res.status);
  return res.json();
}

async function errorDetail(res: Response): Promise<string> {
  try {
    const data = await res.json();
    return typeof data.detail === "string" ? data.detail : `Request failed (${res.status}).`;
  } catch {
    return `Request failed (${res.status}).`;
  }
}

async function postStream(url: string, body: unknown, password: string, handlers: StreamHandlers, signal?: AbortSignal): Promise<void> {
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...authHeaders(password),
    },
    body: JSON.stringify(body),
    signal,
  });

  if (res.status === 401) {
    throw new ApiError("Incorrect password.", 401);
  }
  if (!res.ok || !res.body) {
    throw new ApiError(res.ok ? `Request failed (${res.status}).` : await errorDetail(res), res.status);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      dispatchEvent(rawEvent, handlers);
    }
  }
}

function dispatchEvent(raw: string, handlers: StreamHandlers) {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return;
  const data = JSON.parse(dataLines.join("\n"));

  if (event === "run") handlers.onRun?.(data.run_id as string);
  else if (event === "progress") handlers.onProgress(data as TraceEntry);
  else if (event === "report") handlers.onReport(data as ReportResult);
  else if (event === "plan_review") handlers.onPlanReview?.(data as PlanReview);
  else if (event === "cancelled") handlers.onCancelled?.();
  else if (event === "error") handlers.onError(data.detail ?? "Something went wrong.");
}
