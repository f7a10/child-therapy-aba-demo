import { formatClock } from "../lib/format";
import { groupEntries } from "../lib/grouping";
import { contextDetails, titleCase, useI18n } from "../lib/i18n";
import type { ChannelEntry } from "../lib/types";
import { Card, SectionTitle, cx } from "./ui";

/**
 * The session strip: confirmed channel events grouped into moments, as marks on
 * the session timeline and as one line per moment. Context notes are labeled as
 * model suggestions. Only events already released by the server are shown.
 */
export function SessionStrip({ entries, duration, videoTime }: {
  entries: ChannelEntry[];
  duration: number | null;
  videoTime: number | null;
}) {
  const { s } = useI18n();
  const groups = groupEntries(entries);
  const span = duration && duration > 0 ? duration : Math.max(videoTime ?? 0, ...entries.map((e) => e.end_time), 1);
  const position = (time: number) => `${Math.min(100, Math.max(0, (time / span) * 100))}%`;
  return (
    <Card aria-labelledby="strip-title">
      <SectionTitle id="strip-title" action={<span className="text-xs text-faint tabular">{groups.length}</span>}>
        {s.strip.title}
      </SectionTitle>
      <div className="px-5 pb-5">
        {/* Session time always runs left to right, whatever the reading direction. */}
        <div className="relative h-8 rounded-lg border border-line bg-surface-2" dir="ltr" aria-hidden>
          {groups.map((group) => (
            <span
              key={group.entries[0]?.entry_id}
              className={cx("absolute top-1 bottom-1 w-1.5 rounded-sm", group.level === "flag" ? "bg-attention" : "bg-muted/60")}
              style={{ left: position(group.start_time) }}
            />
          ))}
          {videoTime !== null && <span className="absolute top-0 bottom-0 w-0.5 bg-ink" style={{ left: position(videoTime) }} />}
        </div>
        {groups.length === 0 ? (
          <p className="mt-3 text-sm text-faint">{s.strip.empty}</p>
        ) : (
          <ol className="scrollbar-thin mt-3 max-h-[300px] divide-y divide-line overflow-y-auto">
            {[...groups].reverse().map((group) => {
              const measured = group.entries.filter((e) => e.origin !== "suggested");
              const notes = [...new Set(group.entries.filter((e) => e.origin === "suggested")
                .map((e) => contextDetails(e.details, s)).filter(Boolean))];
              const kinds = [...new Set(measured.map((e) => s.kind[e.kind] ?? titleCase(e.kind)))];
              return (
                <li
                  key={group.entries[0]?.entry_id}
                  className={cx("flex items-start gap-3 py-2.5 text-sm", group.level === "flag" && "text-attention")}
                >
                  <time className="shrink-0 pt-0.5 font-mono text-[11px] text-faint tabular" dir="ltr">
                    {formatClock(group.start_time)}
                  </time>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">
                      {group.level === "flag" ? "⚠ " : ""}
                      {kinds.join(" + ") || s.kind.context_note}
                    </p>
                    <p className="text-xs text-muted">
                      {s.activity[group.entries[0]!.activity]} · {s.level[group.level]}
                      {notes.length > 0 && <> · <span className="italic">{s.strip.suggestion}: {notes.join(s.dir === "rtl" ? "؛ " : "; ")}</span></>}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </Card>
  );
}
