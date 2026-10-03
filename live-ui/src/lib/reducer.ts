import type { TimelineLabel } from "./i18n";
import type {
  Activity,
  ChannelEntry,
  EngineSnapshot,
  Identity,
  RecorderStatus,
  RecordingArtifact,
  LiveEvent,
  Observation,
  SessionSnapshot,
  SessionState,
  StreamReady,
} from "./types";

export type Connection = "idle" | "connecting" | "live" | "reconnecting" | "closed";
export type Tone = "neutral" | "attention" | "critical" | "positive";

export interface TimelineItem {
  key: string;
  sequence: number;
  kind: "state" | "identity" | "alert" | "error" | "activity";
  videoTime: number | null;
  /** Rendered in the current language by i18n.timelineText. */
  label: TimelineLabel;
  tone: Tone;
  repeat: number;
  code?: string;
}

export interface LiveState {
  snapshot: SessionSnapshot | null;
  sessionState: SessionState | null;
  lastSequence: number;
  videoTime: number | null;
  identity: Identity | null;
  observation: Observation | null;
  engine: EngineSnapshot | null;
  activity: Activity;
  /** Channel events released so far (causal). */
  entries: ChannelEntry[];
  /** The flagged entry shown as the review card, until acknowledged or invalidated. */
  flag: ChannelEntry | null;
  flagCount: number;
  observationCount: number;
  providerErrors: number;
  latencyMs: number | null;
  /** Age of the latest result relative to the session clock, and whether it exceeded the stale limit. */
  ageS: number | null;
  analysisStale: boolean;
  staleCount: number;
  performance: { p50: number; p95: number; maxAgeS: number } | null;
  recorder: RecorderStatus | null;
  recording: RecordingArtifact | null;
  timeline: TimelineItem[];
  termination: { reason: string; recorded: boolean } | null;
  connection: Connection;
  gapDetected: boolean;
}

export type Action =
  | { type: "reset" }
  | { type: "snapshot"; snapshot: SessionSnapshot }
  | { type: "stream_ready"; ready: StreamReady }
  | { type: "event"; event: LiveEvent }
  | { type: "connection"; status: Connection }
  | { type: "dismiss_flag"; entryId: string };

export const TERMINAL: readonly SessionState[] = ["completed", "failed"];
const TIMELINE_LIMIT = 150;

export const initialState: LiveState = {
  snapshot: null,
  sessionState: null,
  lastSequence: 0,
  videoTime: null,
  identity: null,
  observation: null,
  engine: null,
  activity: "table",
  entries: [],
  flag: null,
  flagCount: 0,
  observationCount: 0,
  providerErrors: 0,
  latencyMs: null,
  ageS: null,
  analysisStale: false,
  staleCount: 0,
  performance: null,
  recorder: null,
  recording: null,
  timeline: [],
  termination: null,
  connection: "idle",
  gapDetected: false,
};

function push(state: LiveState, item: Omit<TimelineItem, "key" | "repeat">): TimelineItem[] {
  const [top, ...rest] = state.timeline;
  if (top && item.kind === "error" && top.kind === "error" && top.code === item.code) {
    return [{ ...top, repeat: top.repeat + 1, videoTime: item.videoTime, sequence: item.sequence }, ...rest];
  }
  return [{ ...item, key: `${item.sequence}-${item.kind}`, repeat: 1 }, ...state.timeline].slice(0, TIMELINE_LIMIT);
}

function applyEvent(state: LiveState, event: LiveEvent): LiveState {
  if (event.sequence <= state.lastSequence) return state; // duplicate after a resume
  const gapDetected = state.gapDetected || (state.lastSequence > 0 && event.sequence > state.lastSequence + 1);
  const next: LiveState = { ...state, lastSequence: event.sequence, gapDetected };

  switch (event.event_type) {
    case "session_state": {
      const terminal = TERMINAL.includes(event.state);
      return {
        ...next,
        sessionState: event.state,
        flag: terminal ? null : next.flag,
        recording: terminal ? event.recording ?? null : next.recording,
        termination: terminal ? { reason: event.reason ?? "unknown", recorded: event.recorded === true } : null,
        timeline: push(next, {
          sequence: event.sequence,
          kind: "state",
          videoTime: next.videoTime,
          label: { type: "state", state: event.state, reason: event.reason },
          tone: event.state === "failed" ? "critical" : event.state === "running" ? "positive" : "neutral",
        }),
      };
    }
    case "identity_state":
      return {
        ...next,
        identity: event.identity,
        // Identity loss invalidates any visible card: it is never shown as current.
        flag: event.identity === "uncertain" ? null : next.flag,
        timeline: push(next, {
          sequence: event.sequence,
          kind: "identity",
          videoTime: event.video_time,
          label: { type: "identity", identity: event.identity },
          tone: event.identity === "confirmed" ? "positive" : "attention",
        }),
      };
    case "observation":
      return {
        ...next,
        observation: event.observation,
        videoTime: event.video_time,
        observationCount: next.observationCount + 1,
        latencyMs: event.processed_monotonic_ms - event.captured_monotonic_ms,
        ageS: event.age_s,
        analysisStale: event.stale,
        staleCount: next.staleCount + (event.stale ? 1 : 0),
      };
    case "engine_state":
      // The engine still tracks identity and activity; its old indicator alerts are not shown.
      return { ...next, engine: event.state, activity: event.state.activity };
    case "channel_event": {
      const entry = event.entry;
      if (next.entries.some((e) => e.entry_id === entry.entry_id)) return next;
      const entries = [...next.entries, entry];
      if (entry.level !== "flag") return { ...next, entries };
      return {
        ...next,
        entries,
        flag: entry,
        flagCount: next.flagCount + 1,
        timeline: push(next, {
          sequence: event.sequence,
          kind: "alert",
          videoTime: entry.start_time,
          label: { type: "flag", kind: entry.kind },
          tone: "attention",
        }),
      };
    }
    case "recording_status":
      return { ...next, recorder: { kind: event.kind, state: event.state, frames: event.frames,
        dropped_frames: event.dropped_frames, pixels_stored: event.pixels_stored } };
    case "performance":
      return {
        ...next,
        recorder: event.recorder,
        performance: { p50: event.provider_ms_p50, p95: event.provider_ms_p95, maxAgeS: event.max_age_s },
      };
    case "activity":
      return {
        ...next,
        activity: event.activity,
        timeline: push(next, {
          sequence: event.sequence,
          kind: "activity",
          videoTime: event.video_time,
          label: { type: "activity", activity: event.activity },
          tone: "neutral",
        }),
      };
    case "error":
      return {
        ...next,
        providerErrors: next.providerErrors + (event.code === "provider_failed" ? 1 : 0),
        timeline: push(next, {
          sequence: event.sequence,
          kind: "error",
          code: event.code,
          videoTime: event.video_time ?? next.videoTime,
          label: { type: "error", code: event.code },
          tone: "critical",
        }),
      };
    default:
      // Forward compatibility: an event type this UI does not know is ignored, never fatal.
      return next;
  }
}

export function reducer(state: LiveState, action: Action): LiveState {
  switch (action.type) {
    case "reset":
      return initialState;
    case "snapshot":
      return {
        ...state,
        snapshot: action.snapshot,
        sessionState: state.lastSequence >= action.snapshot.last_sequence ? state.sessionState : action.snapshot.state,
      };
    case "stream_ready":
      return { ...state, snapshot: action.ready.snapshot, connection: "live" };
    case "connection":
      return { ...state, connection: action.status };
    case "dismiss_flag":
      return state.flag?.entry_id === action.entryId ? { ...state, flag: null } : state;
    case "event":
      return applyEvent(state, action.event);
  }
}
