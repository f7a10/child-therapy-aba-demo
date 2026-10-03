import type { SessionState } from "./types";

/** Largest gap allowed between the shown video and the session clock before re-seeking. */
export const MAX_DRIFT_S = 0.35;

/**
 * hidden: nothing to show yet; follow: the video tracks the session clock (no
 * seeking ahead of what the session has reached); review: the session ended and
 * the therapist may move freely through the recording.
 */
export function videoMode(state: SessionState | null): "hidden" | "follow" | "review" {
  if (state === "completed" || state === "failed") return "review";
  if (state === null || state === "created") return "hidden";
  return "follow";
}

export function videoSeekTarget(current: number, sessionTime: number | null): number | null {
  if (sessionTime === null || !Number.isFinite(sessionTime)) return null;
  return Math.abs(current - sessionTime) > MAX_DRIFT_S ? sessionTime : null;
}
