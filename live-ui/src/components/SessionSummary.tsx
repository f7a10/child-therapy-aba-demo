import type { ReactNode } from "react";
import { Download } from "lucide-react";
import { library } from "../lib/api";
import { formatLength } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { IntervalRow, SessionMeasures } from "../lib/types";
import { SectionTitle, cx } from "./ui";

const percent = (share: number | null | undefined) => (share === null || share === undefined ? null : Math.round(share * 100));

/**
 * The session in ABA data-sheet terms: how long the child sat, stood, lay or was
 * away from the work area, each episode with its duration, and the interval sheet.
 * Everything comes from measured (or inferred) readings; unmeasured time is shown
 * as such and never counted.
 */
export function SessionSummary({ measures, sessionId, onSeek, printable = false }: {
  measures: SessionMeasures;
  sessionId: string;
  /** Review page: jump the video to an episode. */
  onSeek?: (time: number) => void;
  /** Report: the interval sheet is always open and nothing is interactive. */
  printable?: boolean;
}) {
  const { s } = useI18n();
  const m = s.measures;
  const { summary } = measures;
  const stats = (kind: "standing" | "lying" | "away_from_area") => {
    const value = summary.episodes[kind];
    return m.episodesValue(value.count, formatLength(value.total), formatLength(value.longest));
  };
  const posture = summary.posture;
  const sitting = percent(posture?.sitting_share);
  const intervals = (
    <IntervalSheet rows={measures.intervals} />
  );

  return (
    <div>
      <p className="mb-3 text-xs text-faint">{m.note}</p>
      <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {posture && (
          <Tile label={m.sitting} value={sitting === null ? m.notMeasured : m.sittingValue(sitting)}
            sub={m.seen(percent(posture.measured_share)!, percent(posture.inferred_share)!)} />
        )}
        {posture && <Tile label={m.standing} value={stats("standing")} />}
        {posture && <Tile label={m.lying} value={stats("lying")} />}
        {summary.area && (
          <Tile label={m.away} value={stats("away_from_area")}
            sub={summary.area.at_area_share === null ? undefined : m.atArea(percent(summary.area.at_area_share)!)} />
        )}
        {summary.large_movements !== null && (
          <Tile label={m.movements} value={String(summary.large_movements)}
            sub={summary.motion?.moving_share == null ? undefined : m.moving(percent(summary.motion.moving_share)!)} />
        )}
      </dl>

      <h3 className="mt-5 mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-muted">{m.episodesTitle}</h3>
      {measures.episodes.length === 0 ? (
        <p className="text-sm text-faint">{m.noEpisodes}</p>
      ) : (
        <ol className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
          {measures.episodes.map((episode) => {
            const content = (
              <>
                <span className="font-mono text-xs text-muted tabular" dir="ltr">
                  {formatLength(episode.start)}–{formatLength(episode.end)}
                </span>
                <span className="font-medium">{m.kind[episode.kind]}</span>
                <span className="text-xs text-muted tabular" dir="ltr">{formatLength(episode.duration)}</span>
                {(!episode.start_seen || !episode.end_seen) && (
                  // Approximate: the start or end fell in an unmeasured stretch.
                  <span
                    className="text-xs text-faint"
                    title={[!episode.start_seen && m.startUnseen, !episode.end_seen && m.endUnseen]
                      .filter(Boolean).join(s.dir === "rtl" ? "، " : ", ")}
                  >
                    ≈
                  </span>
                )}
              </>
            );
            return (
              <li key={`${episode.kind}-${episode.start}`} className="break-inside-avoid">
                {onSeek && !printable ? (
                  <button
                    onClick={() => onSeek(episode.start)}
                    className="flex w-full flex-wrap items-baseline gap-x-2 rounded-lg border border-line px-3 py-1.5 text-start text-sm transition-colors hover:bg-surface-2"
                  >
                    {content}
                  </button>
                ) : (
                  <div className="flex flex-wrap items-baseline gap-x-2 rounded-lg border border-line px-3 py-1.5 text-sm">{content}</div>
                )}
              </li>
            );
          })}
        </ol>
      )}

      <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted">{m.intervalsTitle(measures.interval_seconds)}</h3>
        {!printable && (
          <div className="flex flex-wrap gap-2">
            {(["intervals", "episodes"] as const).map((kind) => (
              <a
                key={kind}
                href={library.exportUrl(sessionId, kind)}
                download
                className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1 text-xs font-medium text-ink transition-colors hover:bg-surface-2"
              >
                <Download className="size-3.5" aria-hidden />
                {kind === "intervals" ? m.downloadIntervals : m.downloadEpisodes}
              </a>
            ))}
          </div>
        )}
      </div>
      <p className="mt-1 mb-2 text-xs text-faint">{m.intervalsNote}</p>
      {printable ? (
        intervals
      ) : (
        <details className="group">
          <summary className="cursor-pointer text-sm font-medium text-accent">{m.show}</summary>
          <div className="mt-2">{intervals}</div>
        </details>
      )}
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-line px-3 py-2.5 break-inside-avoid">
      <dt className="text-xs text-faint">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium">{value}</dd>
      {sub && <dd className="mt-0.5 text-[11px] text-muted">{sub}</dd>}
    </div>
  );
}

function IntervalSheet({ rows }: { rows: IntervalRow[] }) {
  const { s } = useI18n();
  const m = s.measures;
  const state = (value: string | null, inferred = false): ReactNode =>
    value === null ? <span className="text-faint">—</span> : (
      <span className={cx(inferred && "italic")}>{(s.review.states[inferred ? `held_${value}` : value] ?? value)}</span>
    );
  const flag = (value: boolean | null): ReactNode =>
    value === null ? <span className="text-faint">—</span> : value ? (
      <span className="font-medium text-attention">{m.yes}</span>
    ) : (
      <span className="text-muted">{m.no}</span>
    );
  return (
    <div className="scrollbar-thin max-h-[420px] overflow-auto rounded-xl border border-line print:max-h-none print:overflow-visible">
      <table className="w-full min-w-[640px] text-xs">
        <thead className="sticky top-0 bg-surface-2 text-muted">
          <tr>
            <th className="px-2 py-1.5 text-start font-medium" rowSpan={2}>{m.columns.interval}</th>
            <th className="px-2 pt-1.5 text-center font-medium" colSpan={3}>{m.columns.atEnd}</th>
            <th className="px-2 pt-1.5 text-center font-medium" colSpan={3}>{m.columns.during}</th>
          </tr>
          <tr>
            {[m.columns.posture, m.columns.area, m.columns.motion, m.columns.outOfSeat, m.columns.away, m.columns.movement].map((label) => (
              <th key={label} className="px-2 pb-1.5 text-start font-normal">{label}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row) => (
            <tr key={row.start} className="break-inside-avoid">
              <td className="px-2 py-1 font-mono tabular" dir="ltr">{formatLength(row.start)}–{formatLength(row.end)}</td>
              <td className="px-2 py-1">{state(row.posture, row.posture_inferred)}</td>
              <td className="px-2 py-1">{state(row.area)}</td>
              <td className="px-2 py-1">{state(row.motion)}</td>
              <td className="px-2 py-1">{flag(row.out_of_seat)}</td>
              <td className="px-2 py-1">{flag(row.away_from_area)}</td>
              <td className="px-2 py-1">{flag(row.large_movement)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The summary inside its own titled card section (review page). */
export function SessionSummaryCard(props: Parameters<typeof SessionSummary>[0] & { title: string }) {
  const { title, ...rest } = props;
  return (
    <section aria-labelledby="summary-title">
      <SectionTitle id="summary-title">{title}</SectionTitle>
      <div className="px-5 pb-5">
        <SessionSummary {...rest} />
      </div>
    </section>
  );
}
