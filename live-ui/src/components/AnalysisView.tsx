import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { motion } from "motion/react";
import { ArrowLeft, Check, CircleCheck, CircleDashed, CircleMinus, CircleX, LoaderCircle } from "lucide-react";
import { analysis, ApiError } from "../lib/api";
import { formatClock } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { Activity, AnalysisStatus, StageStatus } from "../lib/types";
import { AREA_NEAR_MAX, areaGap, freePoint } from "../lib/selection";
import { FramePicker, boxesAt, type Click, type Region } from "./FramePicker";
import { Button, Card, cx } from "./ui";

const ACTIVITIES: Activity[] = ["table", "movement", "break"];
const POLL_MS = 700;

/** One in-app analysis: choose the child, follow progress, reselect when asked. */
export function AnalysisView({ jobId, onHome, onReview }: {
  jobId: string;
  onHome: () => void;
  onReview: (sessionId: string) => void;
}) {
  const { s } = useI18n();
  const [status, setStatus] = useState<AnalysisStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [gone, setGone] = useState(false);

  const refresh = useCallback(
    () =>
      analysis.status(jobId).then(setStatus, (reason: unknown) => {
        if (reason instanceof ApiError && reason.status === 404) setGone(true);
      }),
    [jobId],
  );

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const act = (request: Promise<AnalysisStatus>) => {
    setError(null);
    request.then(setStatus, (reason: unknown) => setError(reason instanceof ApiError ? reason.message : "server_down"));
  };

  const cancel = () => {
    void analysis.discard(jobId).then(onHome);
  };

  const errorText = (code: string) => s.analysis.errors[code] ?? s.analysis.errorCode(code);

  return (
    <motion.main
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="mx-auto max-w-[1280px] px-5 pt-6 pb-20 lg:px-8"
    >
      <button onClick={onHome} className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4 rtl:rotate-180" aria-hidden /> {s.analysis.back}
      </button>
      <h1 className="text-2xl font-semibold tracking-tight">
        {s.analysis.title}
        {status && <span className="text-muted"> · {status.title}</span>}
      </h1>

      {gone && (
        <p role="alert" className="mt-5 rounded-xl border border-critical/30 bg-critical-soft px-4 py-3 text-sm text-critical">
          {s.workspace.lost}
        </p>
      )}

      {!status && !gone && <Waiting text={s.analysis.preparing} />}
      {status?.state === "preparing" && <Waiting text={s.analysis.preparing} />}

      {(status?.state === "select" || status?.state === "reselect") && status.frame && (
        <Selector
          key={status.state}
          status={status}
          error={error && errorText(error)}
          onSelect={(selection) => act(analysis.select(jobId, selection))}
          onSkip={() => act(analysis.skip(jobId))}
          onContinue={() => act(analysis.continueWithout(jobId))}
          onCancel={cancel}
        />
      )}

      {status && status.state !== "select" && status.state !== "preparing" && (
        <Progress status={status} onCancel={cancel} onReview={onReview} onHome={onHome} errorText={errorText} />
      )}
    </motion.main>
  );
}

function Waiting({ text }: { text: string }) {
  return (
    <Card className="mt-6 flex items-center gap-3 p-6 text-muted">
      <LoaderCircle className="size-5 animate-spin text-accent" aria-hidden />
      <span role="status">{text}</span>
    </Card>
  );
}

function Selector({ status, error, onSelect, onSkip, onContinue, onCancel }: {
  status: AnalysisStatus;
  error: string | null;
  onSelect: (selection: { x: number; y: number; activity?: Activity; task_region?: Region | null; title?: string }) => void;
  onSkip: () => void;
  onContinue: () => void;
  onCancel: () => void;
}) {
  const { s } = useI18n();
  const frame = status.frame!;
  const initial = status.state === "select";
  const [click, setClick] = useState<Click | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [activity, setActivity] = useState<Activity>("table");
  const [title, setTitle] = useState(status.title);
  const [drawing, setDrawing] = useState(false);
  const [region, setRegion] = useState<Region | null>(null);
  // A click inside overlapping people: where it was and whose boxes, until one is named.
  const [overlap, setOverlap] = useState<{ x: number; y: number; ids: number[] } | null>(null);
  const [focus, setFocus] = useState<number | null>(null);

  // A new frame (after skipping ahead) clears the click; the session settings stay.
  useEffect(() => {
    setClick(null);
    setHint(null);
    setOverlap(null);
    setFocus(null);
  }, [frame.version]);

  const choose = (x: number, y: number) => {
    const hits = boxesAt(frame.boxes, x, y);
    setOverlap(null);
    setFocus(null);
    if (hits.length === 1) {
      setClick({ x, y, boxId: hits[0]!.id });
      setHint(null);
    } else if (hits.length > 1) {
      setClick(null);
      setHint(null);
      setOverlap({ x, y, ids: hits.map((hit) => hit.id) });
    } else {
      setClick(null);
      setHint(s.analysis.errors.click_not_on_person!);
    }
  };

  // The therapist named one of the overlapping people: click a part of them no one else covers.
  const pick = (id: number) => {
    const point = overlap && freePoint(frame.boxes, id, overlap);
    setOverlap(null);
    setFocus(null);
    if (point) {
      setClick({ ...point, boxId: id });
      setHint(null);
    } else {
      setHint(s.analysis.noFreePoint);
    }
  };

  const submit = () => {
    if (!click) return;
    onSelect(initial ? { x: click.x, y: click.y, activity, task_region: region, title } : { x: click.x, y: click.y });
  };

  return (
    <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
      <Card className="p-4">
        <h2 className="text-lg font-semibold">{initial ? s.analysis.selectTitle : s.analysis.reselectTitle}</h2>
        <p className="mt-1 mb-4 text-sm text-muted">
          {initial ? s.analysis.selectBody : s.analysis.reselectBody(formatClock(frame.time))}
        </p>
        <FramePicker
          src={analysis.frameUrl(status.id, frame.version)}
          width={frame.width}
          height={frame.height}
          boxes={frame.boxes}
          click={click}
          onClick={choose}
          drawing={drawing}
          region={region}
          onRegion={(next) => {
            setRegion(next);
            setDrawing(false);
          }}
          alt={initial ? s.analysis.selectTitle : s.analysis.reselectTitle}
          candidates={overlap?.ids}
          focus={focus}
        />
        {overlap && (
          <div role="alert" className="mt-3 rounded-xl border border-attention-line bg-attention-soft px-4 py-3 text-sm text-attention">
            <p>{s.analysis.whichPerson}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {overlap.ids.map((id, index) => (
                <Button
                  key={id}
                  onClick={() => pick(id)}
                  onMouseEnter={() => setFocus(id)}
                  onMouseLeave={() => setFocus(null)}
                  onFocus={() => setFocus(id)}
                  onBlur={() => setFocus(null)}
                >
                  {s.analysis.person(index + 1)}
                </Button>
              ))}
            </div>
          </div>
        )}
        {(hint || error) && (
          <p role="alert" className="mt-3 rounded-xl border border-attention-line bg-attention-soft px-4 py-2.5 text-sm text-attention">
            {hint ?? error}
          </p>
        )}
      </Card>

      <Card className="flex flex-col gap-5 self-start p-5 lg:sticky lg:top-20">
        {initial ? (
          <>
            <Step n={1} title={s.analysis.stepChild} done={Boolean(click)}>
              <p className={cx("text-sm", click ? "font-medium text-positive" : "text-muted")}>
                {click ? s.analysis.chosen : s.analysis.notChosen}
              </p>
            </Step>
            <Step n={2} title={s.analysis.stepDetails} done={Boolean(title.trim())}>
              <label className="grid gap-1.5 text-sm">
                <span className="text-muted">{s.analysis.sessionTitle}</span>
                <input
                  value={title}
                  maxLength={120}
                  onChange={(event) => setTitle(event.target.value)}
                  className="h-10 rounded-lg border border-line-strong bg-surface px-3 text-ink outline-none focus:border-accent"
                />
              </label>
              <fieldset className="grid gap-1.5 text-sm">
                <legend className="mb-1.5 text-muted">{s.analysis.activity}</legend>
                <div className="grid grid-cols-3 gap-1.5">
                  {ACTIVITIES.map((value) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setActivity(value)}
                      aria-pressed={activity === value}
                      className={cx(
                        "rounded-lg border px-2 py-2 text-xs font-medium transition-colors",
                        activity === value ? "border-accent bg-accent-soft text-accent" : "border-line text-muted hover:bg-surface-2",
                      )}
                    >
                      {s.activity[value]}
                    </button>
                  ))}
                </div>
                <span className="text-xs text-faint">{s.analysis.activityHint}</span>
              </fieldset>
            </Step>
            <Step n={3} title={s.analysis.taskArea} done={Boolean(region)}>
              <span className="text-xs text-faint">{s.analysis.taskHint}</span>
              {region && click && (() => {
                // Checked against the child selected on this frame: the area should take in the child's seat.
                const box = frame.boxes.find((b) => b.id === click.boxId);
                if (!box) return null;
                const inside = areaGap(box.xyxy, region) <= AREA_NEAR_MAX;
                return (
                  <p role="status" className={cx("rounded-lg px-2.5 py-1.5 text-xs", inside ? "bg-positive-soft text-positive" : "bg-attention-soft text-attention")}>
                    {inside ? s.analysis.areaOk : s.analysis.areaOff}
                  </p>
                );
              })()}
              <div className="flex gap-2">
                <Button variant={drawing ? "primary" : "secondary"} onClick={() => setDrawing(!drawing)}>
                  {drawing ? s.analysis.drawing : region ? s.analysis.redraw : s.analysis.draw}
                </Button>
                {region && (
                  <Button variant="ghost" onClick={() => setRegion(null)}>
                    {s.analysis.clear}
                  </Button>
                )}
              </div>
            </Step>
            <div className="grid gap-2">
              <Button variant="primary" size="lg" disabled={!click || !title.trim()} onClick={submit}>
                {s.analysis.start}
              </Button>
              <Button variant="secondary" onClick={onSkip}>
                {s.analysis.skip}
              </Button>
            </div>
          </>
        ) : (
          <>
            <p className={cx("text-sm font-medium", click ? "text-positive" : "text-muted")}>
              {click ? `✓ ${s.analysis.chosen}` : s.analysis.notChosen}
            </p>
            <Button variant="primary" size="lg" disabled={!click} onClick={submit}>
              {s.analysis.confirm}
            </Button>
            <Button variant="secondary" onClick={onSkip}>
              {s.analysis.skip}
            </Button>
            <Button variant="ghost" onClick={onContinue}>
              {s.analysis.continueWithout}
            </Button>
            <p className="text-xs text-faint">{s.analysis.reselections(status.reselections, status.max_reselections)}</p>
          </>
        )}
        <Button variant="quiet-danger" onClick={onCancel}>
          {s.analysis.cancel}
        </Button>
      </Card>
    </div>
  );
}

/** One numbered step of the selection form; the number turns into a check once it is filled in. */
function Step({ n, title, done, children }: { n: number; title: string; done: boolean; children: ReactNode }) {
  return (
    <section className="grid gap-2">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <span
          className={cx(
            "grid size-6 shrink-0 place-items-center rounded-full text-xs tabular",
            done ? "bg-positive text-surface" : "bg-surface-2 text-muted ring-1 ring-line-strong",
          )}
          aria-hidden
        >
          {done ? <Check className="size-3.5" /> : n}
        </span>
        {title}
      </h3>
      <div className="grid gap-2 ps-8">{children}</div>
    </section>
  );
}

const STAGE_ICON: Record<StageStatus, typeof CircleCheck> = {
  pending: CircleDashed,
  running: LoaderCircle,
  done: CircleCheck,
  skipped: CircleMinus,
  failed: CircleX,
};

function Progress({ status, onCancel, onReview, onHome, errorText }: {
  status: AnalysisStatus;
  onCancel: () => void;
  onReview: (id: string) => void;
  onHome: () => void;
  errorText: (code: string) => string;
}) {
  const { s } = useI18n();
  const percent = status.progress && status.progress.total > 0 ? Math.round((status.progress.done / status.progress.total) * 100) : null;
  const finished = status.state === "done" || status.state === "failed" || status.state === "cancelled";
  return (
    <Card className={cx("mt-6 p-6", status.state === "reselect" && "opacity-60")}>
      <h2 className="text-lg font-semibold" role="status" aria-live="polite">
        {status.state === "done"
          ? s.analysis.done
          : status.state === "failed"
            ? s.analysis.failed
            : status.state === "cancelled"
              ? s.analysis.cancelled
              : s.analysis.running}
      </h2>
      {!finished && <p className="mt-1 text-sm text-muted">{s.analysis.runningHint}</p>}
      <ol className="mt-5 grid gap-3">
        {status.stages.map((stage) => {
          const Icon = STAGE_ICON[stage.status];
          const running = stage.status === "running";
          return (
            <li key={stage.name} className="flex items-center gap-3 text-sm">
              <Icon
                className={cx(
                  "size-5 shrink-0",
                  running && "animate-spin text-accent",
                  stage.status === "done" && "text-positive",
                  stage.status === "failed" && "text-critical",
                  (stage.status === "pending" || stage.status === "skipped") && "text-faint",
                )}
                aria-hidden
              />
              <span className="w-40 shrink-0 font-medium">{s.analysis.stages[stage.name]}</span>
              <span className="text-muted">
                {s.analysis.status[stage.status]}
                {stage.note && ` · ${s.analysis.notes[stage.note] ?? stage.note}`}
              </span>
              {running && percent !== null && (
                <span className="ms-auto flex w-40 items-center gap-2" dir="ltr">
                  <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                    <span className="block h-full rounded-full bg-accent transition-[width]" style={{ width: `${percent}%` }} />
                  </span>
                  <span className="w-9 text-end font-mono text-xs text-muted">{percent}%</span>
                </span>
              )}
            </li>
          );
        })}
      </ol>
      {status.child_confirmed_fraction !== null && (
        <p className="mt-4 text-sm text-muted">{s.analysis.childConfirmed(Math.round(status.child_confirmed_fraction * 100))}</p>
      )}
      {status.state === "failed" && status.error && (
        <p role="alert" className="mt-4 rounded-xl border border-critical/30 bg-critical-soft px-4 py-3 text-sm text-critical">
          {errorText(status.error)}
        </p>
      )}
      <div className="mt-6 flex flex-wrap gap-3">
        {status.state === "done" && status.session_id && (
          <Button variant="primary" size="lg" onClick={() => onReview(status.session_id!)}>
            {s.analysis.openReview}
          </Button>
        )}
        {finished ? (
          <Button variant="secondary" onClick={onHome}>
            {s.analysis.back}
          </Button>
        ) : (
          <Button variant="quiet-danger" onClick={onCancel}>
            {s.analysis.cancel}
          </Button>
        )}
      </div>
    </Card>
  );
}
