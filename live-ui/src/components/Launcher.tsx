import { useEffect, useState } from "react";
import { motion } from "motion/react";
import {
  ArrowRight,
  CircleAlert,
  CircleDashed,
  EyeOff,
  FileVideo,
  Hand,
  HardDrive,
  Hourglass,
  LayoutPanelTop,
  PersonStanding,
  PlugZap,
  ScanEye,
  ShieldCheck,
  Timer,
  UserCheck,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../lib/api";
import { SCENARIO_TEXT, useI18n } from "../lib/i18n";
import { CHANNELS, type Scenario } from "../lib/types";
import { Button, Card, Pill } from "./ui";

const SCENARIO_ICON: Record<string, LucideIcon> = {
  "table-routine": LayoutPanelTop,
  "leaves-seat": PersonStanding,
  "brief-occlusion": EyeOff,
  "partial-visibility": ScanEye,
  "analysis-failures": CircleAlert,
  "source-disconnect": PlugZap,
  "slow-analysis": Hourglass,
  "recorder-failure": HardDrive,
  "precomputed-replay": FileVideo,
};

const PRINCIPLE_ICONS = [UserCheck, CircleDashed, Hand];

interface Props {
  onStart: (scenarioId: string) => void;
  creating: boolean;
  error: string | null;
}

export function Launcher({ onStart, creating, error }: Props) {
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const { s } = useI18n();

  useEffect(() => {
    api.scenarios().then(setScenarios, () => setLoadError("server_down"));
  }, []);

  return (
    <motion.main
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      className="mx-auto max-w-[1440px] px-5 pb-20 lg:px-8"
    >
      <section className="grid gap-10 pt-12 pb-10 lg:grid-cols-[1.1fr_1fr] lg:items-end lg:pt-20">
        <div>
          <Pill tone="attention" className="mb-5">
            <ShieldCheck className="size-3.5" aria-hidden /> {s.launcher.badge}
          </Pill>
          <h1 className="max-w-[16ch] text-4xl font-semibold tracking-[-0.03em] text-balance sm:text-5xl lg:text-6xl">
            {s.launcher.heading}
          </h1>
          <p className="mt-5 max-w-[56ch] text-[17px] leading-relaxed text-muted text-pretty">
            {s.launcher.intro}
          </p>
        </div>
        <ul className="grid gap-3">
          {s.launcher.principles.map(({ title, body }, index) => {
            const Icon = PRINCIPLE_ICONS[index] ?? Hand;
            return (
            <motion.li
              key={title}
              initial={{ opacity: 0, x: 12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.1 + index * 0.08, duration: 0.4 }}
              className="flex gap-4 rounded-2xl border border-line bg-surface/70 p-4"
            >
              <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
                <Icon className="size-5" aria-hidden />
              </span>
              <div>
                <p className="font-medium">{title}</p>
                <p className="text-sm text-muted">{body}</p>
              </div>
            </motion.li>
            );
          })}
        </ul>
      </section>

      <div className="mb-5 flex flex-wrap items-end justify-between gap-3 border-t border-line pt-8">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">{s.launcher.chooseTitle}</h2>
          <p className="mt-1 text-sm text-muted">{s.launcher.chooseBody}</p>
        </div>
      </div>

      {scenarios?.length === 0 && !loadError && (
        <p className="mb-5 rounded-xl border border-line bg-surface-2 px-4 py-3 text-sm text-muted">{s.launcher.empty}</p>
      )}

      {(loadError || error) && (
        <p role="alert" className="mb-5 rounded-xl border border-critical/30 bg-critical-soft px-4 py-3 text-sm text-critical">
          {loadError ? s.launcher.serverDown : error}
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {(scenarios ?? Array.from({ length: 8 }, () => null)).map((scenario, index) =>
          scenario ? (
            <ScenarioCard
              key={scenario.id}
              scenario={scenario}
              index={index}
              busy={creating && chosen === scenario.id}
              disabled={creating}
              onStart={() => {
                setChosen(scenario.id);
                onStart(scenario.id);
              }}
            />
          ) : (
            <div key={index} className="h-[228px] animate-pulse rounded-2xl border border-line bg-surface-2" />
          ),
        )}
      </div>
    </motion.main>
  );
}

function ScenarioCard({ scenario, index, busy, disabled, onStart }: {
  scenario: Scenario;
  index: number;
  busy: boolean;
  disabled: boolean;
  onStart: () => void;
}) {
  const { s, language } = useI18n();
  const Icon = SCENARIO_ICON[scenario.id] ?? LayoutPanelTop;
  const recorded = scenario.kind === "precomputed";
  const channelNames = CHANNELS.filter((channel) => scenario.channels?.includes(channel)).map((channel) => s.channel[channel]);
  const text = recorded
    ? { title: scenario.title, summary: s.launcher.recordedSummary(channelNames.join(language === "ar" ? "، " : ", ")) }
    : SCENARIO_TEXT[language]?.[scenario.id] ?? { title: scenario.title, summary: scenario.summary };
  const tags = recorded ? channelNames : scenario.exercises;
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
    >
      <Card className="group flex h-full flex-col p-5 transition-[border-color,transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:border-line-strong">
        <div className="flex items-start justify-between gap-3">
          <span className="grid size-11 place-items-center rounded-xl bg-surface-2 text-accent ring-1 ring-line transition-colors group-hover:bg-accent-soft">
            <Icon className="size-5" aria-hidden />
          </span>
          <div className="flex flex-col items-end gap-1.5">
            <Pill tone={recorded ? "positive" : "neutral"}>{recorded ? s.launcher.recordedPill : s.launcher.simulationPill}</Pill>
            {scenario.duration_s != null && (
              <span className="inline-flex items-center gap-1 font-mono text-xs text-muted" dir="ltr">
                <Timer className="size-3.5" aria-hidden />
                {scenario.duration_s}s{scenario.fps ? ` · ${Math.round(scenario.fps)} fps` : ""}
              </span>
            )}
          </div>
        </div>
        <h3 className="mt-4 text-lg font-semibold tracking-tight">{text.title}</h3>
        <p className="mt-1.5 flex-1 text-sm leading-relaxed text-muted">{text.summary}</p>
        <div className="mt-4 flex flex-wrap gap-1.5">
          {tags.map((tag) => (
            <span key={tag} className="rounded-md bg-surface-2 px-2 py-0.5 text-[11px] text-muted">
              {tag}
            </span>
          ))}
        </div>
        <Button
          variant="secondary"
          className="mt-5 w-full group-hover:border-accent/50 group-hover:text-accent"
          onClick={onStart}
          loading={busy}
          disabled={disabled}
          aria-label={`${recorded ? s.launcher.open : s.launcher.launch}: ${text.title}`}
        >
          {recorded ? s.launcher.open : s.launcher.launch}
          <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5 rtl:rotate-180" aria-hidden />
        </Button>
      </Card>
    </motion.div>
  );
}
