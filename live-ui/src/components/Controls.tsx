import { useEffect, useState } from "react";
import { Check, Crosshair, Pause, Play, Power, RotateCcw, Square, Undo2 } from "lucide-react";
import type { Command, SessionState } from "../lib/types";
import { useI18n } from "../lib/i18n";
import { Button, Kbd, cx } from "./ui";

const STEPS: SessionState[][] = [
  ["created"],
  ["previewing"],
  ["target_selected", "running", "paused", "stopping"],
  ["completed", "failed"],
];

interface Props {
  state: SessionState | null;
  pending: string | null;
  onCommand: (command: Command) => void;
  onRestart: () => void;
  onLeave: () => void;
  /** Recorded sessions: the child was selected during analysis, so the step is a confirmation. */
  recorded?: boolean;
}

export function Controls({ state, pending, onCommand, onRestart, onLeave, recorded = false }: Props) {
  const [confirmStop, setConfirmStop] = useState(false);
  const { s } = useI18n();
  const current = STEPS.findIndex((states) => state !== null && states.includes(state));

  useEffect(() => {
    if (!confirmStop) return;
    const timer = setTimeout(() => setConfirmStop(false), 3500);
    return () => clearTimeout(timer);
  }, [confirmStop]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.code !== "Space" || target?.closest("button, input, select, textarea")) return;
      if (state === "running") onCommand("pause");
      else if (state === "paused") onCommand("resume");
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state, onCommand]);

  const busy = (command: Command) => pending === command;
  const stop = () => {
    if (!confirmStop) return setConfirmStop(true);
    setConfirmStop(false);
    onCommand("stop");
  };

  return (
    <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <ol className="flex items-center gap-1.5" aria-label={s.controls.progress}>
        {STEPS.map((_, index) => {
          const done = index < current;
          const active = index === current;
          return (
            <li key={index} className="flex items-center gap-1.5">
              <span
                className={cx(
                  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
                  active && "bg-accent-soft text-accent",
                  done && "text-muted",
                  !active && !done && "text-faint",
                )}
                aria-current={active ? "step" : undefined}
              >
                <span
                  className={cx(
                    "grid size-4 place-items-center rounded-full text-[10px]",
                    active ? "bg-accent text-accent-ink" : done ? "bg-surface-2 text-muted" : "border border-line-strong",
                  )}
                >
                  {done ? <Check className="size-2.5" aria-hidden /> : index + 1}
                </span>
                <span className="hidden md:inline">{s.controls.steps[index]}</span>
              </span>
              {index < STEPS.length - 1 && <span className="h-px w-3 bg-line-strong md:w-5" aria-hidden />}
            </li>
          );
        })}
      </ol>

      <div className="flex flex-wrap items-center gap-2">
        {state === "created" && (
          <Button variant="primary" icon={<Power className="size-4" />} loading={busy("open")} onClick={() => onCommand("open")}>
            {s.controls.open}
          </Button>
        )}
        {state === "previewing" && (
          <Button variant="primary" icon={<Crosshair className="size-4" />} loading={busy("select_target")} onClick={() => onCommand("select_target")}>
            {recorded ? s.controls.confirmChild : s.controls.lock}
          </Button>
        )}
        {state === "target_selected" && (
          <Button variant="primary" icon={<Play className="size-4" />} loading={busy("start")} onClick={() => onCommand("start")}>
            {s.controls.start}
          </Button>
        )}
        {state === "running" && (
          <Button icon={<Pause className="size-4" />} loading={busy("pause")} onClick={() => onCommand("pause")}>
            {s.controls.pause} <Kbd>Space</Kbd>
          </Button>
        )}
        {state === "paused" && (
          <Button variant="primary" icon={<Play className="size-4" />} loading={busy("resume")} onClick={() => onCommand("resume")}>
            {s.controls.resume} <Kbd>Space</Kbd>
          </Button>
        )}
        {(state === "running" || state === "paused") && (
          <Button
            variant="quiet-danger"
            icon={<Square className="size-3.5" />}
            loading={busy("stop")}
            onClick={stop}
            aria-live="polite"
          >
            {confirmStop ? s.controls.confirmEnd : s.controls.end}
          </Button>
        )}
        {(state === "completed" || state === "failed") && (
          <>
            <Button icon={<RotateCcw className="size-4" />} onClick={onRestart}>
              {s.controls.again}
            </Button>
            <Button variant="primary" icon={<Undo2 className="size-4" />} onClick={onLeave}>
              {s.controls.newSession}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
