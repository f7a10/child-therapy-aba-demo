import { useEffect, useRef } from "react";
import type { SessionState } from "../lib/types";
import { videoMode, videoSeekTarget } from "../lib/videoSync";

export interface SeekRequest {
  time: number;
  nonce: number;
}

/**
 * The replayed session's own video (served from loopback, SHA-bound at startup).
 * While the session runs it follows the session clock, so it never shows a moment
 * the session has not reached; after the session ends it is free for review and
 * jumps to moments chosen on the session strip.
 */
export function ReplayVideo({ sessionId, state, videoTime, seek, label }: {
  sessionId: string;
  state: SessionState | null;
  videoTime: number | null;
  seek: SeekRequest | null;
  label: string;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const mode = videoMode(state);

  useEffect(() => {
    const video = ref.current;
    if (!video || mode !== "follow") return;
    const target = videoSeekTarget(video.currentTime, videoTime);
    if (target !== null) video.currentTime = target;
    if (state === "running" && video.paused) void video.play().catch(() => {});
    if (state !== "running" && !video.paused) video.pause();
  }, [mode, state, videoTime]);

  useEffect(() => {
    const video = ref.current;
    if (!video || mode !== "review" || !seek) return;
    video.currentTime = seek.time;
    video.pause();
  }, [mode, seek]);

  if (mode === "hidden") return null;
  return (
    <video
      ref={ref}
      src={`/api/live/sessions/${encodeURIComponent(sessionId)}/video`}
      className="absolute inset-0 size-full bg-black object-contain"
      muted
      playsInline
      preload="auto"
      controls={mode === "review"}
      aria-label={label}
    />
  );
}
