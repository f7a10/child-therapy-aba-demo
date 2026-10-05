import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { motion } from "motion/react";
import { Activity, ArrowLeft, Compass, FileText, MessageSquareText, PersonStanding } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { library } from "../lib/api";
import { formatClock, formatLength } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { groupEntries } from "../lib/grouping";
import { CHANNELS, type ChannelEntry, type ChannelName, type ClinicianMark, type ReviewPayload, type Verdict } from "../lib/types";
import { ReviewTimeline } from "./ReviewTimeline";
import { SessionStrip } from "./SessionStrip";
import { Button, Card, SectionTitle, cx } from "./ui";

const ICON: Record<ChannelName, LucideIcon> = {
  posture: PersonStanding,
  movement: Activity,
  orientation: Compass,
  context: MessageSquareText,
};
/** Seconds of lead-in shown before a moment when watching it. */
const LEAD_IN_S = 2;

/** Review of one analysed session: its video, the channel lanes and the moments. */
export function ReviewView({ sessionId, onHome, onReport }: { sessionId: string; onHome: () => void; onReport: () => void }) {
  const { s, language } = useI18n();
  const [review, setReview] = useState<ReviewPayload | null>(null);
  const [failed, setFailed] = useState(false);
  const [videoTime, setVideoTime] = useState(0);
  const [marks, setMarks] = useState<Record<string, ClinicianMark>>({});
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    library.review(sessionId).then((payload) => {
      setReview(payload);
      setMarks(payload.clinician);
    }, () => setFailed(true));
  }, [sessionId]);

  // The server returns every mark after a change, so the page always shows what is stored.
  const mark = async (momentId: string, verdict: Verdict | null, note: string) => {
    const result = await library.mark(sessionId, momentId, verdict, note);
    setMarks(result.clinician);
  };

  // The playhead follows the video smoothly while it plays.
  useEffect(() => {
    let frame = 0;
    const tick = () => {
      if (video.current) setVideoTime(video.current.currentTime);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [review]);

  const entries = useMemo<ChannelEntry[]>(
    () => (review?.entries ?? []).map((entry) => ({ ...entry, event_id: entry.source_event_id })),
    [review],
  );
  const momentCount = useMemo(() => groupEntries(entries).length, [entries]);
  const reviewed = Object.keys(marks).length;

  const seek = (time: number) => {
    if (video.current) video.current.currentTime = time;
  };
  const watch = (time: number) => {
    seek(Math.max(0, time - LEAD_IN_S));
    void video.current?.play().catch(() => {});
  };

  if (failed) {
    return (
      <main className="mx-auto max-w-[1440px] px-5 pt-8 lg:px-8">
        <p role="alert" className="rounded-xl border border-critical/30 bg-critical-soft px-4 py-3 text-sm text-critical">
          {s.review.loadError}
        </p>
      </main>
    );
  }

  const date = review?.created
    ? new Date(review.created).toLocaleString(language === "ar" ? "ar" : "en", { dateStyle: "medium", timeStyle: "short" })
    : null;

  return (
    <motion.main
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="mx-auto max-w-[1440px] px-5 pt-6 pb-20 lg:px-8"
    >
      <button onClick={onHome} className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4 rtl:rotate-180" aria-hidden /> {s.review.back}
      </button>
      {!review ? (
        <div className="h-[420px] animate-pulse rounded-2xl border border-line bg-surface-2" />
      ) : (
        <>
          <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{review.title}</h1>
              {date && <p className="mt-1 text-sm text-muted">{s.review.analysed(date)}</p>}
            </div>
            <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
              <dl className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                <Fact label={s.review.duration} value={<span dir="ltr">{formatLength(review.duration)}</span>} />
                <Fact label={s.review.activity} value={s.activity[review.activity]} />
                {review.child_confirmed_fraction !== null && (
                  <Fact label={s.review.childConfirmed} value={`${Math.round(review.child_confirmed_fraction * 100)}%`} />
                )}
              </dl>
              <Button onClick={onReport} icon={<FileText className="size-4" aria-hidden />}>
                {s.verdict.report}
              </Button>
            </div>
          </header>

          {/* The moments sit beside the video and scroll within its height, so watching one needs no page scroll. */}
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_400px]">
            <Card className="overflow-hidden">
              <video
                ref={video}
                src={library.videoUrl(review.id)}
                className="aspect-video w-full bg-black object-contain"
                controls
                playsInline
                preload="auto"
                aria-label={s.stage.video}
              />
              <div className="px-5 pt-4 pb-5">
                <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                  <h2 className="text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">{s.review.timeline}</h2>
                  <span className="font-mono text-xs text-muted" dir="ltr">
                    {formatClock(videoTime)} / {formatClock(review.duration)}
                  </span>
                </div>
                <ReviewTimeline review={review} videoTime={videoTime} onSeek={seek} />
                <p className="mt-2 text-xs text-faint">{s.review.timelineHint}</p>
              </div>
            </Card>

            <div className="relative min-w-0">
              <div className="xl:absolute xl:inset-0">
                <SessionStrip
                  entries={entries}
                  duration={review.duration}
                  videoTime={videoTime}
                  onWatch={watch}
                  hideBar
                  fill
                  title={s.review.momentsTitle}
                  marks={marks}
                  onMark={mark}
                  action={momentCount > 0 && (
                    <span className={cx("text-xs tabular", reviewed === momentCount ? "font-medium text-positive" : "text-faint")}>
                      {s.verdict.progress(reviewed, momentCount)}
                    </span>
                  )}
                />
              </div>
            </div>
          </div>

          <Card aria-labelledby="channels-summary" className="mt-6">
            <SectionTitle id="channels-summary">{s.review.channelsTitle}</SectionTitle>
            <ul className="grid gap-3 px-4 pb-4 sm:grid-cols-2 xl:grid-cols-4">
              {CHANNELS.map((channel) => (
                <ChannelRow key={channel} channel={channel} review={review} videoTime={videoTime} />
              ))}
            </ul>
          </Card>
        </>
      )}
    </motion.main>
  );
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-faint">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

function ChannelRow({ channel, review, videoTime }: { channel: ChannelName; review: ReviewPayload; videoTime: number }) {
  const { s } = useI18n();
  const Icon = ICON[channel];
  const loaded = review.channels.includes(channel);
  const summary = review.summary[channel];
  const count = review.entries.filter((entry) => entry.channel === channel).length;
  const flagged = review.entries.some((entry) => entry.channel === channel && entry.level === "flag");
  const band = summary?.bands?.find(([start, end]) => start <= videoTime && videoTime < end);
  const reason = review.skipped[channel];
  const checks = review.entries.filter((entry) => entry.channel === channel && entry.details.second_opinion === "disagrees").length;
  return (
    <li
      className={cx(
        "min-w-0 rounded-xl border p-3",
        !loaded ? "hatched border-dashed border-line-strong" : flagged ? "border-attention-line bg-attention-soft/50" : "border-line",
      )}
    >
      <div className="flex items-start gap-2.5">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted">
          <Icon className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold leading-tight">{s.channel[channel]}</p>
          <p className="text-[11px] leading-snug text-faint">{s.basis[channel]}</p>
        </div>
        {loaded && <span className={cx("shrink-0 pt-0.5 text-xs font-medium", count ? "text-ink" : "text-muted")}>{s.review.events(count)}</span>}
      </div>
      <div className="mt-2 text-xs text-muted">
        {!loaded ? (
          <span>
            {s.review.notAnalysed} · {reason ? s.review.reasons[reason] ?? reason : s.review.notInSession}
          </span>
        ) : channel === "context" ? (
          <span>
            {s.review.contextRead(summary?.read ?? 0, summary?.moments ?? 0)}
            {checks > 0 && <span className="font-medium text-attention"> · {s.strip.checkBadge}: {checks}</span>}
          </span>
        ) : (
          <div className="grid gap-0.5">
            <span>{s.review.measured(Math.round((summary?.coverage ?? 0) * 100))}</span>
            {count === 0 && <span className="font-medium text-ink">{s.review.noEventObserved}</span>}
            {summary?.bands && (
              <span>
                {s.review.now}: {band ? <span className="font-medium text-ink">{s.review.states[band[2]] ?? band[2]}</span> : s.review.notMeasuredNow}
              </span>
            )}
          </div>
        )}
      </div>
    </li>
  );
}
