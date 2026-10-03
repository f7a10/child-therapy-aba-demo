import { describe, expect, it } from "vitest";
import { initialState, reducer, type LiveState } from "./reducer";
import type { ChannelEntry, EngineEvent, EngineSnapshot, LiveEvent } from "./types";

const base = { schema_version: 1, session_id: "synthetic", provider: "synthetic", monotonic_ms: 0 };

function apply(state: LiveState, ...events: Array<Record<string, unknown>>): LiveState {
  return events.reduce<LiveState>(
    (acc, event) => reducer(acc, { type: "event", event: { ...base, ...event } as LiveEvent }),
    state,
  );
}

const alert: EngineEvent = {
  id: 1, type: "out_of_seat", start: 0, end: null, duration: 2, alerted_at: 2, evidence_time: 2,
};

function entry(overrides: Partial<ChannelEntry> = {}): ChannelEntry {
  return { event_id: "pos-000000", entry_id: "tl-posture-pos-000000", channel: "posture", kind: "stand_to_sit",
    origin: "measured", start_time: 31.4, end_time: 31.6, detected_time: 32, evidence_times: [31.4, 31.6],
    clinician_confirmation: "pending", details: {}, activity: "table", level: "info", ...overrides };
}

function engine(overrides: Partial<EngineSnapshot> = {}): EngineSnapshot {
  return { time: 2, activity: "table", identity: "confirmed", indicators: {} as EngineSnapshot["indicators"],
    events: [alert], alert: null, ...overrides };
}

describe("live reducer", () => {
  it("ignores duplicate sequences after a resume", () => {
    const once = apply(initialState, { sequence: 1, event_type: "session_state", state: "created" });
    const twice = apply(once, { sequence: 1, event_type: "session_state", state: "failed" });
    expect(twice).toBe(once);
  });

  it("ignores unknown event types instead of failing", () => {
    const state = apply(initialState, { sequence: 1, event_type: "from_a_newer_server", payload: 1 });
    expect(state.lastSequence).toBe(1);
    expect(state.timeline).toHaveLength(0);
  });

  it("flags sequence gaps", () => {
    const state = apply(initialState,
      { sequence: 1, event_type: "session_state", state: "created" },
      { sequence: 5, event_type: "session_state", state: "previewing" });
    expect(state.gapDetected).toBe(true);
  });

  it("never surfaces the old engine alert as the review card", () => {
    const state = apply(initialState, { sequence: 1, event_type: "engine_state", video_time: 2, state: engine({ alert }) });
    expect(state.flag).toBeNull();
    expect(state.flagCount).toBe(0);
  });

  it("collects channel events and raises only flagged ones as the card", () => {
    const info = apply(initialState, { sequence: 1, event_type: "channel_event", video_time: 32, entry: entry() });
    expect(info.entries).toHaveLength(1);
    expect(info.flag).toBeNull();
    const flagged = apply(info, { sequence: 2, event_type: "channel_event", video_time: 101,
      entry: entry({ entry_id: "tl-posture-pos-000001", kind: "sit_to_stand", level: "flag", start_time: 100 }) });
    expect(flagged.flag?.entry_id).toBe("tl-posture-pos-000001");
    expect(flagged.flagCount).toBe(1);
    expect(flagged.timeline[0]?.kind).toBe("alert");
    const again = apply(flagged, { sequence: 3, event_type: "channel_event", video_time: 102,
      entry: entry({ entry_id: "tl-posture-pos-000001", level: "flag" }) });
    expect(again.entries).toHaveLength(2);
    const dismissed = reducer(flagged, { type: "dismiss_flag", entryId: "tl-posture-pos-000001" });
    expect(dismissed.flag).toBeNull();
    expect(dismissed.flagCount).toBe(1);
  });

  it("clears the visible card when identity becomes uncertain", () => {
    const flagged = apply(initialState, { sequence: 1, event_type: "channel_event", video_time: 101,
      entry: entry({ level: "flag" }) });
    const lost = apply(flagged, { sequence: 2, event_type: "identity_state", identity: "uncertain", video_time: 3 });
    expect(lost.flag).toBeNull();
    expect(lost.entries).toHaveLength(1);
    expect(lost.timeline[0]?.label).toEqual({ type: "identity", identity: "uncertain" });
  });

  it("clears the card and records termination on failure", () => {
    const flagged = apply(initialState, { sequence: 1, event_type: "channel_event", video_time: 101,
      entry: entry({ level: "flag" }) });
    const failed = apply(flagged, {
      sequence: 2, event_type: "session_state", state: "failed", reason: "source_disconnected", recorded: false,
    });
    expect(failed.flag).toBeNull();
    expect(failed.termination).toEqual({ reason: "source_disconnected", recorded: false });
  });

  it("collapses repeated provider errors", () => {
    const error = { event_type: "error", code: "provider_failed", detail: "x" };
    const state = apply(initialState, { sequence: 1, ...error, video_time: 1 }, { sequence: 2, ...error, video_time: 1.2 });
    expect(state.timeline).toHaveLength(1);
    expect(state.timeline[0]?.repeat).toBe(2);
    expect(state.providerErrors).toBe(2);
  });

});
