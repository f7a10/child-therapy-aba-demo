import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, CircleAlert, CircleCheckBig, Hourglass, TriangleAlert, WifiOff, X } from "lucide-react";
import { formatDuration } from "../lib/format";
import { scenarioTitle, titleCase, useI18n } from "../lib/i18n";
import { TERMINAL } from "../lib/reducer";
import type { LiveSessionController } from "../lib/useLiveSession";
import { Controls } from "./Controls";
import { ChannelTiles } from "./ChannelTiles";
import { SessionStrip } from "./SessionStrip";
import { ActivitySwitch, CandidateCard, SessionFacts, Timeline } from "./SidePanel";
import type { SeekRequest } from "./ReplayVideo";
import { Stage } from "./Stage";
import { Card, Pill, cx } from "./ui";

export function Workspace({ live, onHome }: { live: LiveSessionController; onHome: () => void }) {
  const { state } = live;
  const { s, language } = useI18n();
  const [seek, setSeek] = useState<SeekRequest | null>(null);
  const session = state.sessionState;
  const terminal = session !== null && TERMINAL.includes(session);
  const streamDown = state.connection === "reconnecting" || state.connection === "connecting";
  // The stream closed for good without a terminal event: the server no longer knows this session.
  const lost = state.connection === "closed" && !terminal;
  const stale = streamDown || terminal || lost;
  const candidate = (
    <CandidateCard
      alert={state.flag}
      onAcknowledge={live.dismissFlag}
      unavailable={stale || state.identity === "uncertain" || state.analysisStale}
    />
  );
  const canChangeActivity = session === "target_selected" || session === "running" || session === "paused";

  return (
    <motion.main
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
      className="mx-auto grid max-w-[1440px] gap-5 px-5 py-6 lg:grid-cols-[minmax(0,1fr)_360px] lg:px-8"
    >
      <nav aria-label={s.workspace.breadcrumb} className="flex min-w-0 items-center gap-3 lg:col-span-2">
        <button
          onClick={onHome}
          className="group inline-flex h-9 items-center gap-2 rounded-xl pe-3 ps-2 text-sm font-medium text-muted transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <ArrowLeft className="size-4 transition-transform group-hover:-translate-x-0.5 rtl:rotate-180" aria-hidden />
          {s.workspace.allScenarios}
        </button>
        <span className="text-line-strong" aria-hidden>/</span>
        <h1 className="truncate text-sm font-semibold tracking-tight">{scenarioTitle(state.snapshot?.scenario, language) ?? s.workspace.session}</h1>
        {session && (
          <Pill tone={session === "failed" ? "critical" : session === "running" ? "positive" : "neutral"}>
            {s.sessionState[session]}
          </Pill>
        )}
      </nav>

      <div className="flex min-w-0 flex-col gap-5">
        <AnimatePresence>
          {live.error && (
            <Banner key="error" tone="critical" icon={<CircleAlert className="size-4" />} onClose={live.clearError} dismissLabel={s.workspace.dismiss}>
              {live.error}
            </Banner>
          )}
          {streamDown && state.lastSequence > 0 && !terminal && (
            <Banner key="stream" tone="attention" icon={<WifiOff className="size-4" />}>
              {s.workspace.streamDown}
            </Banner>
          )}
          {lost && (
            <Banner key="lost" tone="critical" icon={<CircleAlert className="size-4" />} action={{ label: s.workspace.newSession, onClick: live.leave }}>
              {s.workspace.lost}
            </Banner>
          )}
          {state.analysisStale && !terminal && (
            <Banner key="late" tone="attention" icon={<Hourglass className="size-4" />}>
              {s.workspace.late(state.ageS?.toFixed(1) ?? "?")}
            </Banner>
          )}
          {state.gapDetected && (
            <Banner key="gap" tone="attention" icon={<TriangleAlert className="size-4" />}>
              {s.workspace.gap}
            </Banner>
          )}
          {terminal && state.termination && <Summary key="summary" live={live} />}
        </AnimatePresence>

        <Card className="overflow-hidden">
          <Stage live={state} stale={streamDown || lost || terminal} canSelect={session === "previewing" && live.pending === null} onSelect={() => live.send("select_target")} seek={seek} />
          <Controls
            state={session}
            pending={live.pending}
            onCommand={(command) => live.send(command)}
            onRestart={() => state.snapshot && live.startScenario(state.snapshot.scenario.id)}
            onLeave={onHome}
          />
        </Card>

        {/* On narrow screens the candidate card sits right under the stage. */}
        <div className="lg:hidden">{candidate}</div>

        <ChannelTiles live={state} stale={stale} />
        <SessionStrip
          entries={state.entries}
          duration={state.snapshot?.scenario.duration_s ?? null}
          videoTime={state.videoTime}
          onWatch={terminal && state.snapshot?.scenario.video ? (time) => setSeek({ time, nonce: Date.now() }) : undefined}
        />
      </div>

      <aside className="flex min-w-0 flex-col gap-5" aria-label={s.workspace.details}>
        <div className="hidden lg:block">{candidate}</div>
        <SessionFacts live={state} snapshot={state.snapshot} />
        <ActivitySwitch
          value={state.activity}
          enabled={canChangeActivity}
          pending={live.pending === "set_activity"}
          onChange={(activity) => live.send("set_activity", activity)}
        />
        <Timeline items={state.timeline} />
      </aside>
    </motion.main>
  );
}

function Banner({ tone, icon, children, onClose, action, dismissLabel = "Dismiss" }: {
  tone: "critical" | "attention";
  icon: React.ReactNode;
  children: React.ReactNode;
  onClose?: () => void;
  action?: { label: string; onClick: () => void };
  dismissLabel?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      role="alert"
      className="overflow-hidden"
    >
      <div
        className={cx(
          "flex items-center gap-3 rounded-xl border px-4 py-3 text-sm",
          tone === "critical" ? "border-critical/30 bg-critical-soft text-critical" : "border-attention-line bg-attention-soft text-attention",
        )}
      >
        {icon}
        <span className="flex-1">{children}</span>
        {action && (
          <button onClick={action.onClick} className="rounded-lg border border-current/30 px-3 py-1 text-xs font-semibold hover:bg-surface/50">
            {action.label}
          </button>
        )}
        {onClose && (
          <button onClick={onClose} className="rounded-md p-1 hover:bg-surface/50" aria-label={dismissLabel}>
            <X className="size-4" />
          </button>
        )}
      </div>
    </motion.div>
  );
}

function Summary({ live }: { live: LiveSessionController }) {
  const { state } = live;
  const { s } = useI18n();
  const failed = state.sessionState === "failed";
  const reason = state.termination?.reason ?? "";
  const stats = [
    [s.workspace.stats.videoTime, formatDuration(state.videoTime ?? 0)],
    [s.workspace.stats.observations, String(state.observationCount)],
    [s.workspace.stats.flags, String(state.flagCount)],
    [s.workspace.stats.gaps, String(state.providerErrors)],
    [s.workspace.stats.late, String(state.staleCount)],
  ];
  return (
    <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
      <Card className={cx("p-5", failed ? "border-critical/30" : "border-positive/25")}>
        <div className="flex flex-wrap items-start gap-4">
          <span className={cx("grid size-11 place-items-center rounded-xl", failed ? "bg-critical-soft text-critical" : "bg-positive-soft text-positive")}>
            {failed ? <CircleAlert className="size-5" aria-hidden /> : <CircleCheckBig className="size-5" aria-hidden />}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-lg font-semibold tracking-tight">{failed ? s.workspace.failed : s.workspace.ended}</p>
            <p className="text-sm text-muted">
              {s.termination[reason] ?? titleCase(reason)}. {s.workspace.noVideo}{" "}
              {state.recording
                ? s.workspace.ledger(state.recording.frames, state.recording.dropped_frames, state.recording.sha256.slice(0, 12))
                : s.workspace.noLedger}
            </p>
          </div>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
          {stats.map(([label, value]) => (
            <div key={label} className="rounded-xl bg-surface-2 px-3 py-2.5">
              <dt className="text-[11px] text-muted">{label}</dt>
              <dd className="text-lg font-semibold tabular">{value}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </motion.div>
  );
}
