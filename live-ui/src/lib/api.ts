import type { Activity, AnalysisStatus, Command, LibrarySession, ReviewPayload, Scenario, SessionSnapshot } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body?.error === "string" ? body.error : `Request failed (${response.status})`;
    throw new ApiError(response.status, detail);
  }
  return body as T;
}

export const api = {
  health: () => request<{ status: string; mode: string }>("/api/live/health"),
  scenarios: () => request<{ scenarios: Scenario[] }>("/api/live/scenarios").then((r) => r.scenarios),
  createSession: (scenario: string) =>
    request<SessionSnapshot>("/api/live/sessions", { method: "POST", body: JSON.stringify({ scenario }) }),
  discardSession: (sessionId: string) =>
    fetch(`/api/live/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }).then(() => undefined),
  command: (sessionId: string, command: Command, activity?: Activity) =>
    request<SessionSnapshot>(`/api/live/sessions/${encodeURIComponent(sessionId)}/commands`, {
      method: "POST",
      body: JSON.stringify(activity ? { command, activity } : { command }),
    }),
};

const analysisPath = (id: string, action = "") => `/api/analyses/${encodeURIComponent(id)}${action}`;

export const library = {
  list: () => request<{ sessions: LibrarySession[]; analysis: boolean }>("/api/library"),
  review: (id: string) => request<ReviewPayload>(`/api/library/${encodeURIComponent(id)}`),
  videoUrl: (id: string) => `/api/library/${encodeURIComponent(id)}/video`,
};

export interface Selection {
  x: number;
  y: number;
  activity?: Activity;
  task_region?: [number, number, number, number] | null;
  title?: string;
}

export const analysis = {
  current: () => request<{ analysis: AnalysisStatus | null }>("/api/analyses/current").then((r) => r.analysis),
  status: (id: string) => request<AnalysisStatus>(analysisPath(id)),
  frameUrl: (id: string, version: number) => `${analysisPath(id, "/frame")}?v=${version}`,
  select: (id: string, selection: Selection) =>
    request<AnalysisStatus>(analysisPath(id, "/select"), { method: "POST", body: JSON.stringify(selection) }),
  skip: (id: string) => request<AnalysisStatus>(analysisPath(id, "/skip"), { method: "POST" }),
  continueWithout: (id: string) => request<AnalysisStatus>(analysisPath(id, "/continue"), { method: "POST" }),
  discard: (id: string) => fetch(analysisPath(id), { method: "DELETE" }).then(() => undefined),
  /** Streams the file to the local server (loopback only), reporting upload progress 0..1. */
  upload: (file: File, onProgress: (fraction: number) => void) =>
    new Promise<AnalysisStatus>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/analyses");
      xhr.setRequestHeader("Content-Type", "application/octet-stream");
      xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
      xhr.upload.onprogress = (event) => event.lengthComputable && onProgress(event.loaded / event.total);
      xhr.onload = () => {
        let body: { error?: string } = {};
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          // fall through to the generic error
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body as AnalysisStatus);
        else reject(new ApiError(xhr.status, typeof body.error === "string" ? body.error : `upload_failed_${xhr.status}`));
      };
      xhr.onerror = () => reject(new ApiError(0, "server_down"));
      xhr.send(file);
    }),
};

export function eventsUrl(sessionId: string, after: number): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/live/sessions/${encodeURIComponent(sessionId)}/events?after=${after}`;
}
