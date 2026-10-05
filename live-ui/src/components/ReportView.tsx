import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { motion } from "motion/react";
import { ArrowLeft, Printer, TriangleAlert } from "lucide-react";
import { library } from "../lib/api";
import { formatClock, formatLength } from "../lib/format";
import { groupEntries } from "../lib/grouping";
import { contextDetails, contextStory, titleCase, useI18n } from "../lib/i18n";
import { CHANNELS, type ChannelEntry, type ReviewPayload } from "../lib/types";
import { BrandMark } from "./TopBar";
import { VERDICTS, VERDICT_ICON, VERDICT_TONE } from "./MomentReview";
import { ContextLines } from "./SessionStrip";
import { SessionSummary } from "./SessionSummary";
import { Button, cx } from "./ui";

/**
 * A printable summary of one reviewed session: what each channel measured, every
 * moment with its model note, and the therapist's own review. Print it, or save it
 * as PDF from the print dialog; nothing is generated or sent anywhere else.
 */
export function ReportView({ sessionId, onBack }: { sessionId: string; onBack: () => void }) {
  const { s, language } = useI18n();
  const [review, setReview] = useState<ReviewPayload | null>(null);
  const [failed, setFailed] = useState(false);
  const [thumbnail, setThumbnail] = useState(true);

  useEffect(() => {
    library.review(sessionId).then(setReview, () => setFailed(true));
  }, [sessionId]);

  const entries = useMemo<ChannelEntry[]>(
    () => (review?.entries ?? []).map((entry) => ({ ...entry, event_id: entry.source_event_id })),
    [review],
  );
  const groups = useMemo(() => groupEntries(entries), [entries]);
  const dateText = (value: string | Date) =>
    new Date(value).toLocaleString(language === "ar" ? "ar" : "en", { dateStyle: "medium", timeStyle: "short" });

  if (failed) {
    return (
      <main className="mx-auto max-w-[960px] px-5 pt-8">
        <p role="alert" className="rounded-xl border border-critical/30 bg-critical-soft px-4 py-3 text-sm text-critical">
          {s.review.loadError}
        </p>
      </main>
    );
  }
  if (!review) {
    return (
      <main className="mx-auto max-w-[960px] px-5 pt-8">
        <div className="h-[520px] animate-pulse rounded-2xl border border-line bg-surface-2" />
      </main>
    );
  }

  const marks = review.clinician;
  const counts = Object.fromEntries(VERDICTS.map((v) => [v, Object.values(marks).filter((m) => m.verdict === v).length]));
  const flags = groups.filter((group) => group.level === "flag").length;

  return (
    <motion.main
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="mx-auto max-w-[960px] px-5 pt-6 pb-20 print:max-w-none print:p-0"
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 print:hidden">
        <button onClick={onBack} className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
          <ArrowLeft className="size-4 rtl:rotate-180" aria-hidden /> {review.title}
        </button>
        <Button variant="primary" onClick={() => window.print()} icon={<Printer className="size-4" aria-hidden />}>
          {s.report.print}
        </Button>
      </div>

      <article className="rounded-2xl border border-line bg-surface p-6 shadow-card sm:p-8 print:rounded-none print:border-0 print:p-0 print:shadow-none">
        <header className="flex flex-wrap items-start justify-between gap-6 border-b border-line pb-6">
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-muted">
              <BrandMark className="size-5" /> {s.topbar.title} · {s.report.title}
            </p>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight">{review.title}</h1>
            <p className="mt-1 text-sm text-muted">
              {review.created && <>{s.review.analysed(dateText(review.created))} · </>}
              {s.report.generated(dateText(new Date()))}
            </p>
          </div>
          {thumbnail && (
            <img
              src={library.thumbnailUrl(review.id)}
              alt=""
              onError={() => setThumbnail(false)}
              className="h-28 w-auto rounded-xl border border-line object-cover"
            />
          )}
        </header>

        <Section title={s.report.overview}>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
            <Stat label={s.review.duration} value={<span dir="ltr">{formatLength(review.duration)}</span>} />
            <Stat label={s.review.activity} value={s.activity[review.activity]} />
            <Stat
              label={s.review.childConfirmed}
              value={review.child_confirmed_fraction === null ? "—" : `${Math.round(review.child_confirmed_fraction * 100)}%`}
            />
            <Stat label={s.report.moments} value={groups.length} />
            <Stat label={s.report.flags} value={flags} />
            <Stat
              label={s.report.reviewed}
              value={
                <span>
                  <span className="tabular">{Object.keys(marks).length}/{groups.length}</span>
                  {Object.keys(marks).length > 0 && (
                    <span className="ms-2 inline-flex flex-wrap gap-1 align-middle">
                      {VERDICTS.filter((v) => counts[v]).map((v) => (
                        <VerdictChip key={v} verdict={v} label={`${s.verdict[v]} ${counts[v]}`} />
                      ))}
                    </span>
                  )}
                </span>
              }
            />
          </dl>
        </Section>

        {review.measures && (
          <Section title={s.measures.title}>
            <SessionSummary measures={review.measures} sessionId={review.id} printable />
          </Section>
        )}

        <Section title={s.report.channels}>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-start text-xs text-muted">
                <th className="py-2 pe-4 text-start font-medium">{s.report.channel}</th>
                <th className="py-2 pe-4 text-start font-medium">{s.report.coverage}</th>
                <th className="py-2 text-start font-medium">{s.report.events}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {CHANNELS.map((channel) => {
                const loaded = review.channels.includes(channel);
                const summary = review.summary[channel];
                const count = review.entries.filter((entry) => entry.channel === channel).length;
                const reason = review.skipped[channel];
                return (
                  <tr key={channel}>
                    <td className="py-2 pe-4 font-medium">{s.channel[channel]}</td>
                    <td className="py-2 pe-4 text-muted">
                      {!loaded
                        ? `${s.report.notAnalysed}${reason ? ` · ${s.review.reasons[reason] ?? reason}` : ""}`
                        : channel === "context"
                          ? s.review.contextRead(summary?.read ?? 0, summary?.moments ?? 0)
                          : `${Math.round((summary?.coverage ?? 0) * 100)}%`
                            + ((summary?.held ?? 0) >= 0.005 ? ` · ${s.review.inferred(Math.round(summary!.held! * 100))}` : "")}
                      {Object.keys(summary?.reasons ?? {}).length > 0 && (
                        <span className="block text-xs text-faint">
                          {s.review.notMeasured}:{" "}
                          {Object.entries(summary!.reasons!)
                            .filter(([, share]) => share >= 0.01)
                            .sort((a, b) => b[1] - a[1])
                            .map(([why, share]) => `${s.review.gapReasons[why] ?? why} ${Math.round(share * 100)}%`)
                            .join(s.dir === "rtl" ? "، " : ", ")}
                        </span>
                      )}
                    </td>
                    <td className="py-2 tabular">{loaded ? count : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Section>

        <Section title={s.report.momentsTitle}>
          {groups.length === 0 ? (
            <p className="text-sm text-muted">{s.report.noMoments}</p>
          ) : (
            <ol className="divide-y divide-line">
              {groups.map((group) => {
                const measured = group.entries.filter((e) => e.origin !== "suggested");
                const suggested = group.entries.filter((e) => e.origin === "suggested");
                const stories = suggested.map((e) => contextStory(e.details, s)).filter((story) => story !== null);
                const notes = [...new Set(suggested.filter((e) => contextStory(e.details, s) === null)
                  .map((e) => contextDetails(e.details, s)).filter(Boolean))];
                const kinds = [...new Set(measured.map((e) => s.kind[e.kind] ?? titleCase(e.kind)))];
                const mark = marks[group.entries[0]!.entry_id];
                return (
                  <li key={group.entries[0]!.entry_id} className="grid gap-3 py-4 break-inside-avoid sm:grid-cols-[72px_minmax(0,1fr)_200px]">
                    <time className="font-mono text-xs text-muted tabular" dir="ltr">{formatClock(group.start_time)}</time>
                    <div className="min-w-0">
                      <p className={cx("font-medium", group.level === "flag" && "text-attention")}>
                        {group.level === "flag" && <TriangleAlert className="me-1 inline size-3.5 align-[-2px]" aria-hidden />}
                        {kinds.join(" + ") || s.kind.context_note}
                      </p>
                      <p className="text-xs text-muted">
                        {s.activity[group.entries[0]!.activity]} · {s.level[group.level]}
                        {notes.length > 0 && <> · <span className="italic">{s.strip.suggestion}: {notes.join(s.dir === "rtl" ? "؛ " : "; ")}</span></>}
                      </p>
                      {stories.map((story, index) => <ContextLines key={index} story={story} />)}
                    </div>
                    <div className="text-sm">
                      <p className="mb-1 text-[11px] font-medium text-faint">{s.report.yourReview}</p>
                      {mark ? (
                        <>
                          <VerdictChip verdict={mark.verdict} label={s.verdict[mark.verdict]} />
                          {mark.note && <p dir="auto" className="mt-1 border-s-2 border-line-strong ps-2 text-xs text-ink">{mark.note}</p>}
                        </>
                      ) : (
                        <p className="text-xs text-faint">{s.report.notReviewed}</p>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </Section>

        <p className="mt-8 rounded-xl bg-surface-2 px-4 py-3 text-xs leading-relaxed text-muted print:border print:border-line">
          {s.report.disclaimer}
        </p>
      </article>
    </motion.main>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-7">
      <h2 className="mb-3 text-[13px] font-semibold uppercase tracking-[0.08em] text-muted break-after-avoid">{title}</h2>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-faint">{label}</dt>
      <dd className="mt-0.5 font-medium">{value}</dd>
    </div>
  );
}

function VerdictChip({ verdict, label }: { verdict: keyof typeof VERDICT_ICON; label: string }) {
  const Icon = VERDICT_ICON[verdict];
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-md border px-1.5 py-px text-[11px] font-medium", VERDICT_TONE[verdict])}>
      <Icon className="size-3" aria-hidden />
      {label}
    </span>
  );
}
