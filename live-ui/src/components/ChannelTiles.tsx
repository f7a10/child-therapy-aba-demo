import { motion } from "motion/react";
import { Activity, Compass, MessageSquareText, PersonStanding } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { CHANNEL_BASIS, CHANNEL_KIND_LABEL, CHANNEL_LABEL, contextDetails, formatClock, titleCase } from "../lib/format";
import type { LiveState } from "../lib/reducer";
import { CHANNELS, type ChannelEntry, type ChannelName } from "../lib/types";
import { cx } from "./ui";

const ICON: Record<ChannelName, LucideIcon> = {
  posture: PersonStanding,
  movement: Activity,
  orientation: Compass,
  context: MessageSquareText,
};

/** One tile per observation channel: whether it is loaded, how many events so far, the latest one. */
export function ChannelTiles({ live, stale }: { live: LiveState; stale: boolean }) {
  const loaded = new Set(live.snapshot?.channels ?? []);
  return (
    <section aria-labelledby="channels-title">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="channels-title" className="text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">
          Observation channels
        </h2>
        <p className="text-xs text-faint">Observable signs only · provisional rules · not clinical labels</p>
      </div>
      <div className={cx("grid grid-cols-2 gap-3 xl:grid-cols-4", stale && "opacity-50")}>
        {CHANNELS.map((channel) => (
          <Tile
            key={channel}
            channel={channel}
            loaded={loaded.has(channel)}
            entries={live.entries.filter((e) => e.channel === channel)}
          />
        ))}
      </div>
    </section>
  );
}

function Tile({ channel, loaded, entries }: { channel: ChannelName; loaded: boolean; entries: ChannelEntry[] }) {
  const Icon = ICON[channel];
  const latest = entries[entries.length - 1];
  const flagged = latest?.level === "flag";
  return (
    <motion.article
      layout
      className={cx(
        "relative flex min-h-[168px] flex-col rounded-2xl border p-4 transition-colors duration-300",
        !loaded ? "border-dashed border-line-strong bg-surface hatched" : flagged ? "border-attention-line bg-attention-soft" : "border-line bg-surface",
      )}
      aria-label={`${CHANNEL_LABEL[channel]}: ${loaded ? `${entries.length} events` : "not loaded"}`}
    >
      <span className={cx("grid size-9 place-items-center rounded-xl", flagged ? "bg-surface/70 text-attention" : "bg-surface-2 text-muted")}>
        <Icon className="size-[18px]" aria-hidden />
      </span>
      <h3 className="mt-3 font-semibold tracking-tight">{CHANNEL_LABEL[channel]}</h3>
      <p className="text-[11px] leading-snug text-faint">{CHANNEL_BASIS[channel]}</p>
      <div className="mt-auto pt-3 text-[12px]">
        {!loaded ? (
          <span className="inline-flex rounded-md bg-surface-2 px-2 py-0.5 text-[11px] font-semibold text-faint ring-1 ring-line-strong">
            Not loaded for this session
          </span>
        ) : latest ? (
          <p className="text-ink">
            <span className="font-mono text-faint tabular">{formatClock(latest.start_time)}</span>{" "}
            {CHANNEL_KIND_LABEL[latest.kind] ?? titleCase(latest.kind)}
            {latest.origin === "suggested" && contextDetails(latest.details) && (
              <span className="block text-muted">{contextDetails(latest.details)}</span>
            )}
          </p>
        ) : (
          <p className="text-muted">No event yet</p>
        )}
        {loaded && <p className="mt-1 text-[11px] text-faint tabular">{entries.length} so far</p>}
      </div>
    </motion.article>
  );
}
