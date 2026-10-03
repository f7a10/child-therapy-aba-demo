import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, MotionConfig } from "motion/react";
import { ConfirmDialog } from "./components/ConfirmDialog";
import { Launcher } from "./components/Launcher";
import { TopBar } from "./components/TopBar";
import { Workspace } from "./components/Workspace";
import { useI18n } from "./lib/i18n";
import { useLiveSession } from "./lib/useLiveSession";

export default function App() {
  const live = useLiveSession();
  const { s } = useI18n();
  const [confirmLeave, setConfirmLeave] = useState(false);

  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [live.sessionId]);

  // Leaving an active session ends it, so ask first; anything else leaves immediately.
  const active = live.state.sessionState === "running" || live.state.sessionState === "paused";
  const goHome = useCallback(() => (active ? setConfirmLeave(true) : live.leave()), [active, live.leave]);

  return (
    <MotionConfig reducedMotion="user">
      <div className="min-h-dvh">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:start-3 focus:z-50 focus:rounded-lg focus:bg-surface focus:px-3 focus:py-2"
        >
          {s.app.skip}
        </a>
        <TopBar
          connection={live.state.connection}
          sessionId={live.sessionId}
          onHome={goHome}
          providerKind={live.state.snapshot?.scenario.kind ?? null}
        />
        <div id="main">
          <AnimatePresence mode="wait">
            {live.sessionId ? (
              <Workspace key={live.sessionId} live={live} onHome={goHome} />
            ) : (
              <Launcher key="launcher" onStart={live.startScenario} creating={live.pending === "create"} error={live.error} />
            )}
          </AnimatePresence>
        </div>
        <footer className="mx-auto max-w-[1440px] px-5 pb-8 text-xs text-faint lg:px-8">
          {s.app.footer}
        </footer>
      </div>
      <ConfirmDialog
        open={confirmLeave}
        title={s.app.leaveTitle}
        body={s.app.leaveBody}
        confirmLabel={s.app.leaveConfirm}
        cancelLabel={s.app.keepSession}
        onCancel={() => setConfirmLeave(false)}
        onConfirm={() => {
          setConfirmLeave(false);
          live.leave();
        }}
      />
    </MotionConfig>
  );
}
