import { describe, expect, it } from "vitest";
import { MAX_DRIFT_S, videoMode, videoSeekTarget } from "./videoSync";

describe("replay video sync", () => {
  it("follows the session clock while observing and is free for review afterwards", () => {
    expect(videoMode("running")).toBe("follow");
    expect(videoMode("paused")).toBe("follow");
    expect(videoMode("target_selected")).toBe("follow");
    expect(videoMode("completed")).toBe("review");
    expect(videoMode("failed")).toBe("review");
    expect(videoMode("previewing")).toBe("follow");
    expect(videoMode("created")).toBe("hidden");
    expect(videoMode(null)).toBe("hidden");
  });

  it("only corrects the video when it drifts from the session clock", () => {
    expect(videoSeekTarget(10.0, 10.0 + MAX_DRIFT_S - 0.01)).toBeNull();
    expect(videoSeekTarget(10.0, 10.5)).toBe(10.5);
    expect(videoSeekTarget(12.0, 10.5)).toBe(10.5);
    expect(videoSeekTarget(10.0, null)).toBeNull();
  });
});
