import type { Activity, ChannelName, SessionState } from "./types";

export const CHANNEL_LABEL: Record<ChannelName, string> = {
  posture: "Posture",
  movement: "Large movement",
  orientation: "Facing the task",
  context: "Context",
};

/** What each channel measures, never what it means clinically. */
export const CHANNEL_BASIS: Record<ChannelName, string> = {
  posture: "Sit ↔ stand from the child's own leg joints",
  movement: "Body centre moved more than one torso length",
  orientation: "Head turned away from the drawn task area",
  context: "Model note on marked moments · suggestion only",
};

export const CHANNEL_KIND_LABEL: Record<string, string> = {
  sit_to_stand: "Stood up",
  stand_to_sit: "Sat down",
  large_movement: "Large movement",
  turned_away_from_task: "Turned away from task",
  turned_back_to_task: "Turned back to task",
  context_note: "Context note",
};

export const CONTEXT_DETAIL_LABEL: Record<string, Record<string, string>> = {
  child_location: { at_table: "at the table", away_from_table: "away from the table", walking: "moving around", on_floor: "on the floor" },
  child_handling_material: { yes: "holding material", no: "not holding material" },
};

/** Closed-enum context details as text; unclear answers are left out. */
export function contextDetails(details: Record<string, string>): string {
  if (details.child_separable === "no") return "child not separable from adult";
  return ["child_location", "child_handling_material"]
    .map((name) => CONTEXT_DETAIL_LABEL[name]?.[details[name] ?? ""])
    .filter(Boolean)
    .join(" · ");
}

export const LEVEL_LABEL: Record<"flag" | "info", string> = { flag: "For review", info: "Info" };

export const SESSION_STATE_LABEL: Record<SessionState, string> = {
  created: "Created",
  previewing: "Preview",
  target_selected: "Target selected",
  running: "Running",
  paused: "Paused",
  stopping: "Stopping",
  completed: "Completed",
  failed: "Failed",
};

export const ACTIVITY_LABEL: Record<Activity, string> = {
  table: "Table work",
  movement: "Movement",
  break: "Break",
};

export const TERMINATION_LABEL: Record<string, string> = {
  user_stop: "Stopped by therapist",
  source_eof: "Source reached its end",
  source_disconnected: "Source disconnected",
  worker_failed: "Analysis worker failed",
  server_shutdown: "Server shut down",
  user_left: "Left by therapist",
  recorder_failed: "Recorder failed",
};

export const ERROR_LABEL: Record<string, string> = {
  provider_failed: "Analysis unavailable for a frame",
  source_disconnected: "Video source disconnected",
  worker_failed: "Analysis worker failed",
  recorder_failed: "Recorder failed — no complete recording",
};

export function formatClock(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "--:--.-";
  const clamped = Math.max(0, seconds);
  const minutes = Math.floor(clamped / 60);
  const rest = clamped - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${rest.toFixed(1).padStart(4, "0")}`;
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

export function titleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
