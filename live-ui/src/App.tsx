import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, MotionConfig } from "motion/react";
import { AnalysisView } from "./components/AnalysisView";
import { ConfirmDialog } from "./components/ConfirmDialog";
import { Home } from "./components/Home";
import { ReviewView } from "./components/ReviewView";
import { TopBar } from "./components/TopBar";
import { Workspace } from "./components/Workspace";
import { useI18n } from "./lib/i18n";
import { useLiveSession } from "./lib/useLiveSession";

/** Pages: home, one analysis in progress, or the review of an analysed session. */
type Route = { page: "home" } | { page: "analysis"; id: string } | { page: "review"; id: string };

function readRoute(): Route {
  const match = /^#\/(analysis|review)\/([\w-]{1,80})$/.exec(window.location.hash);
  return match ? { page: match[1] as "analysis" | "review", id: match[2]! } : { page: "home" };
}

export default function App() {
  const live = useLiveSession();
  const { s } = useI18n();
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [route, setRoute] = useState<Route>(readRoute);

  useEffect(() => {
    const onHash = () => setRoute(readRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = useCallback((next: Route) => {
    window.location.hash = next.page === "home" ? "" : `#/${next.page}/${next.id}`;
    setRoute(next);
  }, []);

  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [live.sessionId, route]);

  // Leaving an active live session ends it, so ask first; anything else leaves immediately.
  const active = live.state.sessionState === "running" || live.state.sessionState === "paused";
  const goHome = useCallback(() => {
    if (live.sessionId) {
      if (active) setConfirmLeave(true);
      else live.leave();
      return;
    }
    go({ page: "home" });
  }, [active, go, live.leave, live.sessionId]);

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
          canGoHome={Boolean(live.sessionId) || route.page !== "home"}
          onHome={goHome}
          providerKind={live.state.snapshot?.scenario.kind ?? null}
        />
        <div id="main">
          <AnimatePresence mode="wait">
            {live.sessionId ? (
              <Workspace key={live.sessionId} live={live} onHome={goHome} />
            ) : route.page === "analysis" ? (
              <AnalysisView
                key={`analysis-${route.id}`}
                jobId={route.id}
                onHome={() => go({ page: "home" })}
                onReview={(id) => go({ page: "review", id })}
              />
            ) : route.page === "review" ? (
              <ReviewView key={`review-${route.id}`} sessionId={route.id} onHome={() => go({ page: "home" })} />
            ) : (
              <Home
                key="home"
                onAnalysis={(id) => go({ page: "analysis", id })}
                onReview={(id) => go({ page: "review", id })}
                onScenario={live.startScenario}
                creatingScenario={live.pending === "create"}
              />
            )}
          </AnimatePresence>
        </div>
        <footer className="mx-auto max-w-[1440px] px-5 pb-8 text-xs text-faint lg:px-8">{s.app.footer}</footer>
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
