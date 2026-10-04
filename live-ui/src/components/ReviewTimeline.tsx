import type { MouseEvent } from "react";
import { formatClock } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { CHANNELS, type ChannelName, type ReviewPayload } from "../lib/types";
import { cx } from "./ui";

const BAND_CLASS: Record<string, string> = {
  sitting: "bg-accent/35",
  standing: "bg-attention/55",
  toward: "bg-positive/35",
  away: "bg-attention/55",
};

/**
 * One lane per channel across the whole session: measured-state bands, a mark per
 * detected moment (flagged ones stand out), and the video position. Clicking a
 * lane jumps the video there. Time always runs left to right.
 */
export function ReviewTimeline({ review, videoTime, onSeek }: {
  review: ReviewPayload;
  videoTime: number;
  onSeek: (time: number) => void;
}) {
  const { s } = useI18n();
  const span = review.duration > 0 ? review.duration : 1;
  const at = (time: number) => `${Math.min(100, Math.max(0, (time / span) * 100))}%`;
  const seek = (event: MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    onSeek(Math.max(0, Math.min(span, ((event.clientX - rect.left) / rect.width) * span)));
  };
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const legend = (["sitting", "standing", "toward", "away"] as const).filter((state) =>
    CHANNELS.some((channel) => review.summary[channel]?.bands?.some((band) => band[2] === state)),
  );

  return (
    <div>
      <div className="grid gap-2">
        {CHANNELS.map((channel) => (
          <Lane key={channel} channel={channel} review={review} at={at} seek={seek} videoTime={videoTime} />
        ))}
        <div className="grid gap-3 sm:grid-cols-[132px_1fr]">
          <span className="hidden sm:block" />
          <div className="relative h-5 font-mono text-[10px] text-faint" dir="ltr">
            {ticks.map((tick) => (
              <span
                key={tick}
                className={cx(
                  "absolute top-0",
                  tick === 0 ? "" : tick === 1 ? "-translate-x-full" : "-translate-x-1/2",
                  // Narrow screens keep only the start, middle and end, so the labels never collide.
                  (tick === 0.25 || tick === 0.75) && "hidden sm:block",
                )}
                style={{ left: `${tick * 100}%` }}
              >
                {formatClock(tick * span).replace(/\.\d$/, "")}
              </span>
            ))}
          </div>
        </div>
      </div>
      {legend.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          {legend.map((state) => (
            <span key={state} className="inline-flex items-center gap-1.5">
              <span className={cx("inline-block h-2.5 w-4 rounded-sm", BAND_CLASS[state])} />
              {s.review.states[state]}
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-3 w-1 rounded-sm bg-attention" />
            {s.level.flag}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-3 w-1 rounded-sm bg-ink/70" />
            {s.level.info}
          </span>
        </div>
      )}
    </div>
  );
}

function Lane({ channel, review, at, seek, videoTime }: {
  channel: ChannelName;
  videoTime: number;
  review: ReviewPayload;
  at: (time: number) => string;
  seek: (event: MouseEvent<HTMLDivElement>) => void;
}) {
  const { s } = useI18n();
  const loaded = review.channels.includes(channel);
  const bands = review.summary[channel]?.bands ?? [];
  const entries = review.entries.filter((entry) => entry.channel === channel);
  const reason = review.skipped[channel];
  return (
    <div className="grid items-center gap-1 sm:grid-cols-[132px_1fr] sm:gap-3">
      <span className="truncate text-xs font-medium text-muted">{s.channel[channel]}</span>
      {loaded ? (
        <div
          className="relative h-10 cursor-pointer overflow-hidden rounded-lg border border-line bg-surface-2"
          dir="ltr"
          onClick={seek}
          role="presentation"
        >
          {bands.map(([start, end, state]) => (
            <span
              key={`${start}-${state}`}
              className={cx("absolute top-0 bottom-0", BAND_CLASS[state] ?? "bg-muted/30")}
              style={{ left: at(start), width: `calc(${at(end)} - ${at(start)})` }}
            />
          ))}
          {entries.map((entry) => (
            <span
              key={entry.entry_id}
              title={`${formatClock(entry.start_time)} · ${s.kind[entry.kind] ?? entry.kind}`}
              className={cx(
                "absolute top-1 bottom-1 w-1.5 -translate-x-1/2 rounded-sm",
                entry.level === "flag" ? "bg-attention ring-2 ring-attention/30" : entry.origin === "suggested" ? "bg-accent" : "bg-ink/70",
              )}
              style={{ left: at(entry.start_time) }}
            />
          ))}
          <span className="pointer-events-none absolute top-0 bottom-0 w-0.5 bg-ink" style={{ left: at(videoTime) }} />
        </div>
      ) : (
        <div className="hatched flex h-10 items-center rounded-lg border border-dashed border-line-strong px-3 text-xs text-faint">
          {s.review.notAnalysed}
          {reason ? ` · ${s.review.reasons[reason] ?? reason}` : ` · ${s.review.notInSession}`}
        </div>
      )}
    </div>
  );
}
