import { motion } from "motion/react";
import { Activity, Compass, MessageSquareText, PersonStanding } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { formatClock } from "../lib/format";
import { contextDetails, titleCase, useI18n } from "../lib/i18n";
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
  const { s } = useI18n();
  const loaded = new Set(live.snapshot?.channels ?? []);
  return (
    <section aria-labelledby="channels-title">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="channels-title" className="text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">
          {s.channels.title}
        </h2>
        <p className="text-xs text-faint">{s.channels.note}</p>
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
  const { s } = useI18n();
  const Icon = ICON[channel];
  const latest = entries[entries.length - 1];
  const flagged = latest?.level === "flag";
  const note = latest?.origin === "suggested" ? contextDetails(latest.details, s) : "";
  return (
    <motion.article
      layout
      className={cx(
        "relative flex min-h-[168px] flex-col rounded-2xl border p-4 transition-colors duration-300",
        !loaded ? "border-dashed border-line-strong bg-surface hatched" : flagged ? "border-attention-line bg-attention-soft" : "border-line bg-surface",
      )}
      aria-label={s.channels.aria(s.channel[channel], loaded ? entries.length : null)}
    >
      <span className={cx("grid size-9 place-items-center rounded-xl", flagged ? "bg-surface/70 text-attention" : "bg-surface-2 text-muted")}>
        <Icon className="size-[18px]" aria-hidden />
      </span>
      <h3 className="mt-3 font-semibold tracking-tight">{s.channel[channel]}</h3>
      <p className="text-[11px] leading-snug text-faint">{s.basis[channel]}</p>
      <div className="mt-auto pt-3 text-[12px]">
        {!loaded ? (
          <span className="inline-flex rounded-md bg-surface-2 px-2 py-0.5 text-[11px] font-semibold text-faint ring-1 ring-line-strong">
            {s.channels.notLoaded}
          </span>
        ) : latest ? (
          <p className="text-ink">
            <span className="font-mono text-faint tabular" dir="ltr">{formatClock(latest.start_time)}</span>{" "}
            {s.kind[latest.kind] ?? titleCase(latest.kind)}
            {note && <span className="block text-muted">{note}</span>}
          </p>
        ) : (
          <p className="text-muted">{s.channels.noEvent}</p>
        )}
        {loaded && <p className="mt-1 text-[11px] text-faint tabular">{s.channels.soFar(entries.length)}</p>}
      </div>
    </motion.article>
  );
}
