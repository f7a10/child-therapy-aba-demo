import { FileClock, FlaskConical, Languages } from "lucide-react";
import { useI18n } from "../lib/i18n";
import type { ProviderKind } from "../lib/types";
import type { Connection } from "../lib/reducer";
import { cx } from "./ui";

const CONNECTION_DOT: Record<Connection, string> = {
  idle: "bg-faint",
  connecting: "bg-attention animate-pulse",
  live: "bg-positive",
  reconnecting: "bg-attention animate-pulse",
  closed: "bg-faint",
};

export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="9" fill="var(--accent)" />
      <circle cx="16" cy="16" r="6.5" fill="none" stroke="var(--accent-ink)" strokeWidth="2.4" />
      <circle cx="16" cy="16" r="2" fill="#f2c979" />
    </svg>
  );
}

export function TopBar({ connection, sessionId, canGoHome, onHome, providerKind }: {
  connection: Connection;
  sessionId: string | null;
  canGoHome: boolean;
  onHome: () => void;
  providerKind: ProviderKind | null;
}) {
  const { s, toggle } = useI18n();
  const replay = providerKind === "precomputed";
  const brand = (
    <>
      <BrandMark className="size-9" />
      <div className="text-start leading-tight">
        <p className="text-[15px] font-semibold tracking-tight">{s.topbar.title}</p>
        <p className="text-xs text-muted">{s.topbar.subtitle}</p>
      </div>
    </>
  );
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/80 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1440px] items-center gap-4 px-5 lg:px-8">
        {canGoHome ? (
          <button
            onClick={onHome}
            className="-ms-2 flex items-center gap-3 rounded-xl px-2 py-1 transition-colors hover:bg-surface-2"
            aria-label={s.topbar.back}
          >
            {brand}
          </button>
        ) : (
          <div className="flex items-center gap-3">{brand}</div>
        )}

        {providerKind && <span
          className="ms-2 hidden items-center gap-1.5 rounded-full border border-attention-line bg-attention-soft px-3 py-1 text-xs font-semibold tracking-wide text-attention sm:inline-flex"
          title={
            replay ? s.topbar.replayHint : s.topbar.simulationHint
          }
        >
          {replay ? <FileClock className="size-3.5" aria-hidden /> : <FlaskConical className="size-3.5" aria-hidden />}
          {replay ? s.topbar.replay : s.topbar.simulation}
        </span>}

        <div className="ms-auto flex items-center gap-4 text-xs text-muted">
          {sessionId && <span className="hidden font-mono md:inline">{sessionId}</span>}
          {sessionId && (
            <span className="inline-flex items-center gap-2" role="status" aria-live="polite">
              <span className={cx("size-2 rounded-full", CONNECTION_DOT[connection])} aria-hidden />
              {s.topbar.connection[connection]}
            </span>
          )}
          <button
            onClick={toggle}
            aria-label={s.topbar.switchLabel}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line px-2.5 text-xs font-medium text-ink transition-colors hover:bg-surface-2"
          >
            <Languages className="size-3.5" aria-hidden />
            {s.topbar.switchTo}
          </button>
        </div>
      </div>
    </header>
  );
}
