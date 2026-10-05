export const INDICATORS = [
  "orientation",
  "body_motion",
  "out_of_seat",
  "hand_motion",
  "posture_change",
] as const;

export type Indicator = (typeof INDICATORS)[number];
export type Signal = boolean | null;
export type Identity = "confirmed" | "uncertain";
export type Activity = "table" | "movement" | "break";
export type SessionState =
  | "created"
  | "previewing"
  | "target_selected"
  | "running"
  | "paused"
  | "stopping"
  | "completed"
  | "failed";
export type IndicatorState = "unobservable" | "not_applicable" | "inactive" | "candidate" | "active";
export type Command = "open" | "select_target" | "start" | "pause" | "resume" | "stop" | "set_activity";

export type ProviderKind = "synthetic" | "precomputed";

/** Observation channels (aba_demo/channel_events.py). */
export type ChannelName = "posture" | "movement" | "orientation" | "context";
export const CHANNELS: readonly ChannelName[] = ["posture", "movement", "orientation", "context"];

/** One unified channel event as released by the server once confirmed (detected_time passed). */
export interface ChannelEntry {
  event_id: string;
  entry_id: string;
  channel: ChannelName;
  kind: string;
  origin: "measured" | "suggested";
  start_time: number;
  end_time: number;
  detected_time: number;
  evidence_times: number[];
  clinician_confirmation: string;
  /** Closed-enum notes of a suggested (model) channel; empty for measured channels. */
  details: Record<string, string>;
  activity: Activity;
  level: "flag" | "info";
}

export interface Scenario {
  id: string;
  title: string;
  summary: string;
  kind: ProviderKind;
  duration_s: number | null;
  fps: number | null;
  exercises: string[];
  channels?: ChannelName[];
  /** True when the server can show this session's own recorded video (replay). */
  video?: boolean;
}

export interface RecorderStatus {
  kind: string;
  state: string;
  frames: number;
  dropped_frames: number;
  pixels_stored: boolean;
}

export interface RecordingArtifact extends RecorderStatus {
  first_time: number | null;
  last_time: number | null;
  sha256: string;
  verified: boolean;
}

export interface SessionSnapshot {
  session_id: string;
  state: SessionState;
  provider: string;
  source: string;
  recording: string;
  recorder: RecorderStatus;
  activity: Activity;
  elapsed_s: number;
  last_video_time: number | null;
  termination_reason: string | null;
  provider_errors: number;
  stale_observations: number;
  channels?: ChannelName[];
  last_sequence: number;
  scenario: Scenario;
}

export interface Observation {
  time: number;
  identity: Identity;
  signals: Record<Indicator, Signal>;
  values: Record<string, unknown>;
}

export interface EngineEvent {
  id: number;
  type: Indicator;
  start: number;
  end: number | null;
  end_reason?: string;
  duration: number;
  alerted_at: number | null;
  evidence_time: number;
}

export interface IndicatorSnapshot {
  state: IndicatorState;
  duration: number;
  count: number;
  observable_seconds: number;
  value: unknown;
}

export interface EngineSnapshot {
  time: number;
  activity: Activity;
  identity: Identity;
  indicators: Record<Indicator, IndicatorSnapshot>;
  events: EngineEvent[];
  alert: EngineEvent | null;
}

interface Envelope {
  schema_version: number;
  session_id: string;
  sequence: number;
  provider: string;
  monotonic_ms: number;
}

export type LiveEvent = Envelope &
  (
    | {
        event_type: "session_state";
        state: SessionState;
        reason?: string;
        simulation?: boolean;
        recorded?: boolean;
        recording?: RecordingArtifact | null;
      }
    | { event_type: "identity_state"; identity: Identity; video_time: number }
    | {
        event_type: "observation";
        source_frame_index: number;
        video_time: number;
        captured_monotonic_ms: number;
        processed_monotonic_ms: number;
        age_s: number;
        stale: boolean;
        observation: Observation;
      }
    | { event_type: "engine_state"; video_time: number; stale: boolean; state: EngineSnapshot }
    | ({ event_type: "recording_status" } & RecorderStatus)
    | {
        event_type: "performance";
        video_time: number;
        frames: number;
        provider_ms_p50: number;
        provider_ms_p95: number;
        provider_ms_max: number;
        max_age_s: number;
        stale_observations: number;
        recorder: RecorderStatus;
      }
    | { event_type: "activity"; activity: Activity; video_time: number | null }
    | { event_type: "channel_event"; video_time: number; entry: ChannelEntry }
    | { event_type: "error"; code: string; detail: string; video_time?: number; source_frame_index?: number }
  );

export interface StreamReady {
  event_type: "stream_ready";
  snapshot: SessionSnapshot;
  history_start: number;
  after: number;
}

/** An analysed session in the library (GET /api/library). */
export interface LibrarySession {
  id: string;
  title: string;
  activity: Activity;
  created: string | null;
  duration: number;
  channels: ChannelName[];
  moments: number;
  flags: number;
  /** Moments the therapist has already marked. */
  reviewed: number;
}

/** One timeline entry of an analysed session (aba_demo/session_timeline.py). */
export interface ReviewEntry {
  entry_id: string;
  channel: ChannelName;
  source_event_id: string;
  kind: string;
  origin: "measured" | "suggested";
  start_time: number;
  end_time: number;
  detected_time: number;
  evidence_times: number[];
  activity: Activity;
  level: "flag" | "info";
  clinician_confirmation: string;
  details: Record<string, string>;
}

/** [start, end, state] runs of a measured state, e.g. sitting / standing. */
export type Band = [number, number, string];

export interface ChannelSummary {
  coverage?: number;
  /** Posture: share of the session with a carried-over (inferred) posture. */
  held?: number;
  /** Work area channel: share with a measured head direction. */
  head_coverage?: number;
  /** Stretches with no reading and why, e.g. [start, end, "knees_hidden"]. */
  gaps?: Band[];
  /** Share of the session per gap reason. */
  reasons?: Record<string, number>;
  bands?: Band[];
  moments?: number;
  read?: number;
}

/** The whole analysed session for review (GET /api/library/{id}). */
export interface ReviewPayload {
  id: string;
  title: string;
  activity: Activity;
  created: string | null;
  duration: number;
  decoded_seconds: number;
  child_confirmed_fraction: number | null;
  channels: ChannelName[];
  skipped: Partial<Record<ChannelName, string>>;
  summary: Partial<Record<ChannelName, ChannelSummary>>;
  entries: ReviewEntry[];
  /** The therapist's marks, by moment id (the moment's first entry id). */
  clinician: Record<string, ClinicianMark>;
  /** Episodes, summary and interval sheet (aba_demo/session_measures.py); null without channels. */
  measures: SessionMeasures | null;
}

export interface Episode {
  kind: "standing" | "lying" | "away_from_area";
  start: number;
  end: number;
  duration: number;
  start_seen: boolean;
  end_seen: boolean;
}

export interface EpisodeStats {
  count: number;
  total: number;
  longest: number;
}

export interface IntervalRow {
  start: number;
  end: number;
  posture: string | null;
  posture_inferred: boolean;
  area: string | null;
  motion: string | null;
  out_of_seat: boolean | null;
  away_from_area: boolean | null;
  large_movement: boolean | null;
}

export interface SessionMeasures {
  episodes: Episode[];
  intervals: IntervalRow[];
  interval_seconds: number;
  summary: {
    episodes: Record<Episode["kind"], EpisodeStats>;
    large_movements: number | null;
    posture?: { measured_share: number; inferred_share: number; sitting_share: number | null };
    area?: { measured_share: number; at_area_share: number | null };
    motion?: { measured_share: number; moving_share: number | null };
  };
}

export type Verdict = "confirmed" | "not_seen" | "unsure";

export interface ClinicianMark {
  verdict: Verdict;
  note: string;
  updated: string;
}

export type AnalysisState = "preparing" | "select" | "running" | "reselect" | "done" | "failed" | "cancelled";
export type AnalysisStageName = "tracking" | "posture" | "movement" | "orientation" | "context";
export type StageStatus = "pending" | "running" | "done" | "skipped" | "failed";

export interface FrameBox {
  id: number;
  /** Normalized [x1, y1, x2, y2]. */
  xyxy: [number, number, number, number];
}

/** One in-app analysis of a new video (GET /api/analyses/{id}). */
export interface AnalysisStatus {
  id: string;
  title: string;
  state: AnalysisState;
  stage: AnalysisStageName | null;
  progress: { done: number; total: number } | null;
  error: string | null;
  frame: { version: number; time: number; width: number; height: number; boxes: FrameBox[] } | null;
  reselections: number;
  max_reselections: number;
  stages: { name: AnalysisStageName; status: StageStatus; note: string | null }[];
  session_id: string | null;
  child_confirmed_fraction: number | null;
}
