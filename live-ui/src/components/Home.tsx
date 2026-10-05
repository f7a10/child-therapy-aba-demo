import { useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";
import { motion } from "motion/react";
import {
  ArrowRight,
  CircleDashed,
  FileVideo,
  FlaskConical,
  Hand,
  ShieldCheck,
  Timer,
  Upload,
  UserCheck,
} from "lucide-react";
import { analysis, ApiError, api, library } from "../lib/api";
import { formatLength } from "../lib/format";
import { SCENARIO_TEXT, useI18n } from "../lib/i18n";
import { CHANNELS, type AnalysisStatus, type LibrarySession, type Scenario } from "../lib/types";
import { Button, Card, Pill, cx } from "./ui";

const PRINCIPLE_ICONS = [UserCheck, CircleDashed, Hand];

interface Props {
  onAnalysis: (jobId: string) => void;
  onReview: (sessionId: string) => void;
  onScenario: (scenarioId: string) => void;
  creatingScenario: boolean;
}

/** Home: analyse a new video, or open an analysed session for review. */
export function Home({ onAnalysis, onReview, onScenario, creatingScenario }: Props) {
  const { s } = useI18n();
  const [sessions, setSessions] = useState<LibrarySession[] | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [current, setCurrent] = useState<AnalysisStatus | null>(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    library.list().then((r) => setSessions(r.sessions), () => setLoadError(true));
    analysis.current().then(setCurrent, () => {});
    api.scenarios().then(setScenarios, () => {});
  }, []);

  return (
    <motion.main
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      className="mx-auto max-w-[1440px] px-5 pb-20 lg:px-8"
    >
      <section className="grid gap-10 pt-10 pb-8 lg:grid-cols-[1.1fr_1fr] lg:items-end lg:pt-14">
        <div>
          <Pill tone="attention" className="mb-5">
            <ShieldCheck className="size-3.5" aria-hidden /> {s.home.badge}
          </Pill>
          <h1 className="max-w-[18ch] text-4xl font-semibold tracking-[-0.03em] text-balance sm:text-5xl">
            {s.home.heading}
          </h1>
          <p className="mt-5 max-w-[60ch] text-[17px] leading-relaxed text-muted text-pretty">{s.home.intro}</p>
        </div>
        <ul className="grid gap-3">
          {s.launcher.principles.map(({ title, body }, index) => {
            const Icon = PRINCIPLE_ICONS[index] ?? Hand;
            return (
              <li key={title} className="flex gap-4 rounded-2xl border border-line bg-surface/70 p-4">
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
                  <Icon className="size-5" aria-hidden />
                </span>
                <div>
                  <p className="font-medium">{title}</p>
                  <p className="text-sm text-muted">{body}</p>
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      {loadError && (
        <p role="alert" className="mb-5 rounded-xl border border-critical/30 bg-critical-soft px-4 py-3 text-sm text-critical">
          {s.home.serverDown}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <UploadCard current={current} onAnalysis={onAnalysis} />
        <LibraryList sessions={sessions} onReview={onReview} />
      </div>

      {scenarios.length > 0 && (
        <section className="mt-12 border-t border-line pt-8" aria-labelledby="engineering-title">
          <h2 id="engineering-title" className="text-lg font-semibold tracking-tight">{s.home.engineeringTitle}</h2>
          <p className="mt-1 text-sm text-muted">{s.home.engineeringBody}</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {scenarios.map((scenario) => (
              <ScenarioCard key={scenario.id} scenario={scenario} disabled={creatingScenario} onStart={() => onScenario(scenario.id)} />
            ))}
          </div>
        </section>
      )}
    </motion.main>
  );
}

function UploadCard({ current, onAnalysis }: { current: AnalysisStatus | null; onAnalysis: (id: string) => void }) {
  const { s } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const send = (file: File | undefined) => {
    if (!file || progress !== null) return;
    setError(null);
    setProgress(0);
    analysis.upload(file, setProgress).then(
      (status) => onAnalysis(status.id),
      (reason: unknown) => {
        setProgress(null);
        setError(reason instanceof ApiError ? reason.message : "server_down");
      },
    );
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    send(event.dataTransfer.files[0]);
  };

  return (
    <Card className="flex flex-col p-6" aria-labelledby="upload-title">
      <h2 id="upload-title" className="text-xl font-semibold tracking-tight">{s.home.newTitle}</h2>
      <p className="mt-1 text-sm leading-relaxed text-muted">{s.home.newBody}</p>
      {current ? (
        <Button variant="primary" size="lg" className="mt-6" onClick={() => onAnalysis(current.id)} icon={<ArrowRight className="size-4 rtl:rotate-180" aria-hidden />}>
          {s.home.resume} · {current.title}
        </Button>
      ) : (
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cx(
            "mt-6 flex flex-1 flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors",
            dragging ? "border-accent bg-accent-soft" : "border-line-strong bg-surface-2/50",
          )}
        >
          <span className="grid size-12 place-items-center rounded-2xl bg-accent-soft text-accent">
            <Upload className="size-6" aria-hidden />
          </span>
          {progress === null ? (
            <>
              <Button variant="primary" size="lg" onClick={() => input.current?.click()}>
                {s.home.choose}
              </Button>
              <p className="text-sm text-faint">{s.home.drop}</p>
            </>
          ) : (
            <div className="w-full max-w-xs" role="status" aria-live="polite">
              <p className="text-sm font-medium">{s.home.uploading(Math.round(progress * 100))}</p>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2" dir="ltr">
                <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${progress * 100}%` }} />
              </div>
            </div>
          )}
          <input
            ref={input}
            type="file"
            accept="video/mp4,video/quicktime,video/webm,.mp4,.m4v,.mov,.webm"
            className="sr-only"
            tabIndex={-1}
            onChange={(event) => send(event.target.files?.[0])}
          />
        </div>
      )}
      {error && (
        <p role="alert" className="mt-4 rounded-xl border border-critical/30 bg-critical-soft px-4 py-3 text-sm text-critical">
          {s.analysis.errors[error] ?? s.analysis.errorCode(error)}
        </p>
      )}
    </Card>
  );
}

function LibraryList({ sessions, onReview }: { sessions: LibrarySession[] | null; onReview: (id: string) => void }) {
  const { s, language } = useI18n();
  const date = (value: string | null) =>
    value ? new Date(value).toLocaleString(language === "ar" ? "ar" : "en", { dateStyle: "medium", timeStyle: "short" }) : null;
  return (
    <Card className="p-6" aria-labelledby="library-title">
      <h2 id="library-title" className="text-xl font-semibold tracking-tight">{s.home.libraryTitle}</h2>
      <p className="mt-1 text-sm text-muted">{s.home.libraryBody}</p>
      {sessions === null ? (
        <div className="mt-5 grid gap-3">
          {[0, 1].map((index) => (
            <div key={index} className="h-[76px] animate-pulse rounded-xl border border-line bg-surface-2" />
          ))}
        </div>
      ) : sessions.length === 0 ? (
        <p className="mt-5 rounded-xl border border-line bg-surface-2 px-4 py-3 text-sm text-muted">{s.home.libraryEmpty}</p>
      ) : (
        <ul className="mt-5 grid gap-3">
          {sessions.map((session) => (
            <li key={session.id}>
              <button
                onClick={() => onReview(session.id)}
                className="group flex w-full items-center gap-4 rounded-xl border border-line bg-surface px-4 py-3 text-start transition-colors hover:border-accent/50 hover:bg-surface-2"
              >
                <Thumbnail id={session.id} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{session.title}</span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                    <span className="inline-flex items-center gap-1 tabular" dir="ltr">
                      <Timer className="size-3.5" aria-hidden />
                      {formatLength(session.duration)}
                    </span>
                    <span>{s.activity[session.activity]}</span>
                    <span>{CHANNELS.filter((c) => session.channels.includes(c)).map((c) => s.channel[c]).join(language === "ar" ? "، " : ", ")}</span>
                    {date(session.created) && <span>{date(session.created)}</span>}
                  </span>
                </span>
                <span className="flex shrink-0 flex-col items-end gap-1">
                  {session.moments === 0 ? (
                    <Pill>{s.home.noMoments}</Pill>
                  ) : (
                    <Pill tone={session.flags ? "attention" : "neutral"}>
                      {session.flags ? s.home.flags(session.flags) : s.home.moments(session.moments)}
                    </Pill>
                  )}
                  {session.moments > 0 && session.reviewed > 0 && (
                    <span className={cx("text-[11px] tabular", session.reviewed === session.moments ? "font-medium text-positive" : "text-faint")}>
                      {s.home.reviewed(session.reviewed, session.moments)}
                    </span>
                  )}
                  <span className="inline-flex items-center gap-1 text-xs font-medium text-accent">
                    {s.home.open}
                    <ArrowRight className="size-3.5 rtl:rotate-180" aria-hidden />
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** A small still of the session's video, or the video icon when there is none. */
function Thumbnail({ id }: { id: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className="grid h-12 w-20 shrink-0 place-items-center overflow-hidden rounded-lg bg-surface-2 text-accent ring-1 ring-line">
      {failed ? (
        <FileVideo className="size-5" aria-hidden />
      ) : (
        <img src={library.thumbnailUrl(id)} alt="" loading="lazy" onError={() => setFailed(true)} className="size-full object-cover" />
      )}
    </span>
  );
}

function ScenarioCard({ scenario, disabled, onStart }: { scenario: Scenario; disabled: boolean; onStart: () => void }) {
  const { s, language } = useI18n();
  const text = SCENARIO_TEXT[language]?.[scenario.id] ?? { title: scenario.title, summary: scenario.summary };
  return (
    <Card className="flex flex-col p-4">
      <div className="flex items-center gap-2 text-muted">
        <FlaskConical className="size-4" aria-hidden />
        <span className="text-xs">{s.launcher.simulationPill}</span>
      </div>
      <h3 className="mt-2 font-semibold tracking-tight">{text.title}</h3>
      <p className="mt-1 flex-1 text-xs leading-relaxed text-muted">{text.summary}</p>
      <Button variant="secondary" className="mt-3" onClick={onStart} disabled={disabled}>
        {s.launcher.launch}
      </Button>
    </Card>
  );
}
