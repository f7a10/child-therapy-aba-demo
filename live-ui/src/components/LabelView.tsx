import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { ArrowLeft, ChevronLeft, ChevronRight } from "lucide-react";
import { library } from "../lib/api";
import { formatLength } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { LabelScore, LabelsState, PointLabel } from "../lib/types";
import { Button, Card, SectionTitle, cx } from "./ui";

const POSTURES = ["sitting", "standing", "lying", "not_visible"] as const;
const AREAS = ["at_area", "away_from_area", "not_visible"] as const;
// Physical keys, so the shortcuts work with an Arabic keyboard layout too.
const POSTURE_KEYS: Record<string, PointLabel["posture"]> = { Digit1: "sitting", Digit2: "standing", Digit3: "lying", Digit0: "not_visible" };
const AREA_KEYS: Record<string, PointLabel["area"]> = { KeyQ: "at_area", KeyW: "away_from_area", KeyE: "not_visible" };

/**
 * Ground-truth labelling: the reviewer says what they see at fixed points (every
 * 5 s) and the page shows how the app's readings compare. Nothing here changes a
 * reading; the labels only measure them.
 */
export function LabelView({ sessionId, onBack }: { sessionId: string; onBack: () => void }) {
  const { s } = useI18n();
  const a = s.accuracy;
  const [state, setState] = useState<LabelsState | null>(null);
  const [title, setTitle] = useState("");
  const [index, setIndex] = useState(0);
  const [failed, setFailed] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    library.labels(sessionId).then((value) => {
      setState(value);
      // Start at the first point not labelled yet.
      const next = value.points.findIndex((point) => !value.labels[point.toFixed(1)]);
      setIndex(next < 0 ? 0 : next);
    }, () => setFailed(true));
    library.review(sessionId).then((review) => setTitle(review.title), () => {});
  }, [sessionId]);

  const point = state?.points[index];
  useEffect(() => {
    if (point === undefined || !video.current) return;
    video.current.pause();
    video.current.currentTime = point;
  }, [point]);

  const current: PointLabel = (point !== undefined && state?.labels[point.toFixed(1)]) || { posture: null, area: null };
  const complete = (label: PointLabel) => label.posture !== null && (!state?.area || label.area !== null);

  const save = useCallback((label: PointLabel) => {
    if (point === undefined || !state) return;
    setSaveFailed(false);
    library.setLabel(sessionId, point, label).then((value) => {
      setState(value);
      if (complete(label) && index < value.points.length - 1) setIndex(index + 1);
    }, () => setSaveFailed(true));
  }, [index, point, sessionId, state]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!state || event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      const forward = s.dir === "rtl" ? "ArrowLeft" : "ArrowRight";
      const backward = s.dir === "rtl" ? "ArrowRight" : "ArrowLeft";
      if (event.code in POSTURE_KEYS) save({ ...current, posture: POSTURE_KEYS[event.code]! });
      else if (state.area && event.code in AREA_KEYS) save({ ...current, area: AREA_KEYS[event.code]! });
      else if (event.key === forward) setIndex((i) => Math.min(state.points.length - 1, i + 1));
      else if (event.key === backward) setIndex((i) => Math.max(0, i - 1));
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, save, s.dir, state]);

  if (failed) {
    return (
      <main className="mx-auto max-w-[1440px] px-5 pt-8 lg:px-8">
        <p role="alert" className="rounded-xl border border-critical/30 bg-critical-soft px-4 py-3 text-sm text-critical">{s.review.loadError}</p>
      </main>
    );
  }

  const done = state ? Object.values(state.labels).filter(complete).length : 0;
  const Prev = s.dir === "rtl" ? ChevronRight : ChevronLeft;
  const Next = s.dir === "rtl" ? ChevronLeft : ChevronRight;

  return (
    <motion.main initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
      className="mx-auto max-w-[1440px] px-5 pt-6 pb-20 lg:px-8">
      <button onClick={onBack} className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4 rtl:rotate-180" aria-hidden /> {a.back}
      </button>
      <h1 className="text-2xl font-semibold tracking-tight">{a.title}{title && <span className="text-muted"> · {title}</span>}</h1>
      <p className="mt-1 max-w-[80ch] text-sm text-muted">{a.intro}</p>

      {!state ? (
        <div className="mt-6 h-[420px] animate-pulse rounded-2xl border border-line bg-surface-2" />
      ) : state.points.length === 0 ? (
        <p className="mt-6 text-sm text-muted">{a.tooShort}</p>
      ) : (
        <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_400px]">
          <Card className="overflow-hidden">
            <video ref={video} src={library.videoUrl(sessionId)} className="aspect-video w-full bg-black object-contain"
              controls playsInline preload="auto" aria-label={s.stage.video} />
            {/* One cell per point: labelled points are filled; click to go to one. */}
            <div className="flex flex-wrap gap-1 p-4" dir="ltr" aria-hidden>
              {state.points.map((value, i) => {
                const label = state.labels[value.toFixed(1)];
                return (
                  <button key={value} tabIndex={-1} onClick={() => setIndex(i)} title={formatLength(value)}
                    className={cx("h-3 w-3 rounded-sm ring-1 ring-line-strong",
                      i === index ? "ring-2 ring-accent" : "",
                      label && complete(label) ? "bg-accent/60" : label ? "bg-accent/25" : "bg-surface-2")} />
                );
              })}
            </div>
          </Card>

          <div className="grid content-start gap-6">
            <Card className="p-5">
              <div className="flex items-baseline justify-between gap-3">
                <p className="font-semibold">{a.point(index + 1, state.points.length)}</p>
                <span className="font-mono text-sm text-muted" dir="ltr">{formatLength(point ?? 0)}</span>
              </div>
              <p className="mt-1 text-xs text-faint">{a.progress(done, state.points.length)}</p>
              <Choice title={a.posture} options={POSTURES} value={current.posture} labels={a.labels}
                onPick={(value) => save({ ...current, posture: value })} />
              {state.area && (
                <Choice title={a.area} options={AREAS} value={current.area} labels={a.labels}
                  onPick={(value) => save({ ...current, area: value })} />
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                <Button onClick={() => setIndex(Math.max(0, index - 1))} disabled={index === 0} icon={<Prev className="size-4" aria-hidden />}>
                  {a.previous}
                </Button>
                <Button onClick={() => setIndex(Math.min(state.points.length - 1, index + 1))} disabled={index >= state.points.length - 1}
                  icon={<Next className="size-4" aria-hidden />}>
                  {a.next}
                </Button>
                {(current.posture || current.area) && (
                  <Button variant="ghost" onClick={() => save({ posture: null, area: null })}>{a.clear}</Button>
                )}
              </div>
              {saveFailed && <p role="alert" className="mt-2 text-xs text-critical">{a.saveError}</p>}
              <p className="mt-3 text-[11px] leading-relaxed text-faint">{a.keys}</p>
            </Card>

            <Card>
              <SectionTitle>{a.resultsTitle}</SectionTitle>
              <div className="grid gap-3 px-5 pb-5">
                {done === 0 ? <p className="text-sm text-faint">{a.noLabels}</p> : (
                  (["posture", "area"] as const).map((channel) => {
                    const score = state.accuracy[channel];
                    return score && score.labeled + score.not_visible > 0 ? <Score key={channel} name={a.channel[channel]!} score={score} /> : null;
                  })
                )}
              </div>
            </Card>
          </div>
        </div>
      )}
    </motion.main>
  );
}

function Choice<T extends string>({ title, options, value, labels, onPick }: {
  title: string;
  options: readonly T[];
  value: T | null;
  labels: Record<string, string>;
  onPick: (value: T) => void;
}) {
  return (
    <fieldset className="mt-4">
      <legend className="mb-1.5 text-sm font-medium">{title}</legend>
      <div className="grid grid-cols-2 gap-1.5">
        {options.map((option) => (
          <button key={option} type="button" aria-pressed={value === option} onClick={() => onPick(option)}
            className={cx("rounded-lg border px-2 py-2 text-sm font-medium transition-colors",
              value === option ? "border-accent bg-accent-soft text-accent" : "border-line text-muted hover:bg-surface-2")}>
            {labels[option]}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

export function Score({ name, score }: { name: string; score: LabelScore }) {
  const { s } = useI18n();
  const a = s.accuracy;
  const read = score.measured.count + score.inferred.count;
  return (
    <div className="rounded-xl border border-line p-3 text-sm">
      <p className="font-semibold">{name}</p>
      <ul className="mt-1 grid gap-0.5 text-xs text-muted">
        {score.labeled > 0 && <li>{a.coverage(read, score.labeled)}</li>}
        <li className="text-ink">{a.measured(score.measured.correct, score.measured.count)}</li>
        {score.inferred.count > 0 && <li className="text-ink">{a.inferred(score.inferred.correct, score.inferred.count)}</li>}
        {score.unverifiable > 0 && <li>{a.unverifiable(score.unverifiable)}</li>}
      </ul>
    </div>
  );
}
