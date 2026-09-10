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

export interface ReportResult {
  question: string;
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

export interface StreamHandlers {
  onProgress: (entry: TraceEntry) => void;
  onReport: (result: ReportResult) => void;
  onError: (message: string) => void;
}

/** Parses a `text/event-stream` body read via fetch (EventSource can't do POST). */
export async function streamReport(
  question: string,
  password: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/report/stream`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...authHeaders(password),
    },
    body: JSON.stringify({ question }),
    signal,
  });

  if (res.status === 401) {
    throw new ApiError("Incorrect password.", 401);
  }
  if (!res.ok || !res.body) {
    throw new ApiError(`Request failed (${res.status}).`, res.status);
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

  if (event === "progress") handlers.onProgress(data as TraceEntry);
  else if (event === "report") handlers.onReport(data as ReportResult);
  else if (event === "error") handlers.onError(data.detail ?? "Something went wrong.");
}
