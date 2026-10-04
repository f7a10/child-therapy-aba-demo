import { useEffect, useRef } from "react";
import { TriangleAlert } from "lucide-react";
import { formatClock } from "../lib/format";
import { groupEntries } from "../lib/grouping";
import { contextDetails, contextStory, titleCase, useI18n, type ContextStory } from "../lib/i18n";
import type { ChannelEntry } from "../lib/types";
import { Card, SectionTitle, cx } from "./ui";

/** Seconds around a moment during which the playing video counts as being at it. */
const ACTIVE_MARGIN_S = 2;

/**
 * The session strip: confirmed channel events grouped into moments, as marks on
 * the session timeline and as one line per moment. Context notes are labeled as
 * model suggestions. Only events already released by the server are shown.
 */
export function SessionStrip({ entries, duration, videoTime, onWatch, hideBar = false, fill = false, title }: {
  entries: ChannelEntry[];
  duration: number | null;
  videoTime: number | null;
  /** Review mode only: jump the recorded video to a moment. */
  onWatch?: (time: number) => void;
  /** The review page draws its own timeline above, so the bar can be left out. */
  hideBar?: boolean;
  /** Fill the parent's height and scroll the list inside it (the review page's side panel). */
  fill?: boolean;
  title?: string;
}) {
  const { s } = useI18n();
  const groups = groupEntries(entries);
  const span = duration && duration > 0 ? duration : Math.max(videoTime ?? 0, ...entries.map((e) => e.end_time), 1);
  const position = (time: number) => `${Math.min(100, Math.max(0, (time / span) * 100))}%`;
  // Review only: the moment the video is at, highlighted and kept in view in the list.
  const active = onWatch && videoTime !== null
    ? groups.findIndex((g) => g.start_time - ACTIVE_MARGIN_S <= videoTime && videoTime <= g.end_time + ACTIVE_MARGIN_S)
    : -1;
  const list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const box = list.current;
    const row = active >= 0 ? box?.querySelector<HTMLElement>(`[data-moment="${active}"]`) : null;
    if (!box || !row) return;
    if (row.offsetTop < box.scrollTop || row.offsetTop + row.offsetHeight > box.scrollTop + box.clientHeight) {
      box.scrollTo({ top: Math.max(0, row.offsetTop - 8), behavior: "smooth" });
    }
  }, [active]);
  return (
    <Card aria-labelledby="strip-title" className={cx(fill && "flex h-full flex-col")}>
      <SectionTitle id="strip-title" action={<span className="text-xs text-faint tabular">{groups.length}</span>}>
        {title ?? s.strip.title}
      </SectionTitle>
      <div className={cx("px-5 pb-5", fill && "flex min-h-0 flex-1 flex-col")}>
        {/* Session time always runs left to right, whatever the reading direction. */}
        {!hideBar && <div className="relative h-8 rounded-lg border border-line bg-surface-2" dir="ltr" aria-hidden>
          {groups.map((group) => (
            <span
              key={group.entries[0]?.entry_id}
              className={cx("absolute top-1 bottom-1 w-1.5 rounded-sm", group.level === "flag" ? "bg-attention" : "bg-muted/60")}
              style={{ left: position(group.start_time) }}
            />
          ))}
          {videoTime !== null && <span className="absolute top-0 bottom-0 w-0.5 bg-ink" style={{ left: position(videoTime) }} />}
        </div>}
        {groups.length === 0 ? (
          <p className="mt-3 text-sm text-faint">{hideBar ? s.strip.emptyReview : s.strip.empty}</p>
        ) : (
          <ol
            ref={list}
            className={cx(
              "scrollbar-thin relative mt-1 divide-y divide-line overflow-y-auto",
              fill ? "max-h-[520px] xl:max-h-none xl:min-h-0 xl:flex-1" : "max-h-[420px]",
            )}
          >
            {(hideBar ? groups.map((g, i) => [g, i] as const) : [...groups.map((g, i) => [g, i] as const)].reverse()).map(([group, index]) => {
              const measured = group.entries.filter((e) => e.origin !== "suggested");
              const suggested = group.entries.filter((e) => e.origin === "suggested");
              const stories = suggested.map((e) => contextStory(e.details, s)).filter((story) => story !== null);
              const notes = [...new Set(suggested.filter((e) => contextStory(e.details, s) === null)
                .map((e) => contextDetails(e.details, s)).filter(Boolean))];
              const check = stories.some((story) => story.opinion === "disagrees");
              const kinds = [...new Set(measured.map((e) => s.kind[e.kind] ?? titleCase(e.kind)))];
              return (
                <li
                  key={group.entries[0]?.entry_id}
                  data-moment={index}
                  aria-current={index === active ? "true" : undefined}
                  className={cx(
                    "flex items-start gap-3 border-s-2 py-2.5 ps-2.5 pe-1 text-sm transition-colors",
                    index === active ? "border-s-accent bg-accent-soft/60" : "border-s-transparent",
                  )}
                >
                  <time className="shrink-0 pt-0.5 font-mono text-[11px] text-faint tabular" dir="ltr">
                    {formatClock(group.start_time)}
                  </time>
                  <div className="min-w-0 flex-1">
                    <p className={cx("font-medium", group.level === "flag" && "text-attention")}>
                      {group.level === "flag" && <TriangleAlert className="me-1 inline size-3.5 align-[-2px]" aria-hidden />}
                      {kinds.join(" + ") || s.kind.context_note}
                      {check && (
                        <span className="ms-2 rounded-md bg-attention-soft px-1.5 py-px text-[11px] font-semibold text-attention ring-1 ring-attention-line">
                          {s.strip.checkBadge}
                        </span>
                      )}
                    </p>
                    <p className="text-xs text-muted">
                      {s.activity[group.entries[0]!.activity]} · {s.level[group.level]}
                      {notes.length > 0 && <> · <span className="italic">{s.strip.suggestion}: {notes.join(s.dir === "rtl" ? "؛ " : "; ")}</span></>}
                    </p>
                    {stories.map((story, index) => <ContextLines key={index} story={story} />)}
                  </div>
                  {onWatch && (
                    <button
                      onClick={() => onWatch(group.start_time)}
                      aria-label={s.strip.watchAria(formatClock(group.start_time))}
                      className="shrink-0 rounded-lg border border-line px-2.5 py-1 text-xs font-medium text-ink transition-colors hover:bg-surface-2"
                    >
                      {s.strip.watch}
                    </button>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </Card>
  );
}

/** A v2 context note: what the nearest adult did before and after, and the model's view of the child. */
function ContextLines({ story }: { story: ContextStory }) {
  const { s } = useI18n();
  const line = (label: string, text: string, experimental: string) =>
    text || experimental ? (
      <p>
        <span className="text-faint">{label}:</span> {text}
        {experimental && (
          <>
            {text && " · "}
            {experimental}{" "}
            <span className="rounded bg-surface-2 px-1 text-[10px] text-faint ring-1 ring-line">{s.strip.experimental}</span>
          </>
        )}
      </p>
    ) : null;
  return (
    <div className="mt-1.5 grid gap-0.5 border-s-2 border-accent/30 ps-2 text-xs text-muted">
      {line(s.strip.before, [story.positionBefore && s.strip.childWas(story.positionBefore), story.before].filter(Boolean).join(" · "), story.experimental.before)}
      {story.position && (
        <p>
          <span className="text-faint">{s.strip.modelSees}:</span> <span className="text-ink">{story.position}</span>
          {story.opinion && (
            <span
              className={cx(
                "ms-1.5 inline-block whitespace-nowrap rounded px-1.5 py-px text-[11px] font-medium",
                story.opinion === "agrees" ? "bg-positive-soft text-positive" : "bg-attention-soft text-attention",
              )}
            >
              {s.strip[story.opinion]}
            </span>
          )}
        </p>
      )}
      {line(s.strip.after, story.after, story.experimental.after)}
      <p className="text-[10px] italic text-faint">{s.strip.suggestion}</p>
    </div>
  );
}
