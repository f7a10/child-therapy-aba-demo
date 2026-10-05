import { motion } from "motion/react";
import { ArrowLeft, Camera } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { Card } from "./ui";

/** How to film a session so the readings can see the child. */
export function GuideView({ onBack }: { onBack: () => void }) {
  const { s } = useI18n();
  return (
    <motion.main initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
      className="mx-auto max-w-[960px] px-5 pt-6 pb-20 lg:px-8">
      <button onClick={onBack} className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4 rtl:rotate-180" aria-hidden /> {s.review.back}
      </button>
      <h1 className="text-2xl font-semibold tracking-tight">{s.guide.title}</h1>
      <p className="mt-1 text-sm text-muted">{s.guide.intro}</p>
      <ol className="mt-6 grid gap-3">
        {s.guide.tips.map((tip, index) => (
          <Card as="div" key={tip.title} className="flex gap-4 p-4">
            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-sm font-semibold text-accent tabular">
              {index + 1}
            </span>
            <div>
              <p className="font-medium">{tip.title}</p>
              <p className="mt-0.5 text-sm text-muted">{tip.body}</p>
            </div>
          </Card>
        ))}
      </ol>
    </motion.main>
  );
}

/** This session's recording advice, from where its readings had gaps. */
export function RecordingCheck({ hints }: { hints: string[] }) {
  const { s } = useI18n();
  return (
    <div className="rounded-xl border border-line px-4 py-3 text-sm">
      <p className="flex items-center gap-2 font-medium">
        <Camera className="size-4 text-muted" aria-hidden /> {s.guide.checkTitle}
      </p>
      {hints.length === 0 ? (
        <p className="mt-1 text-xs text-muted">{s.guide.noHints}</p>
      ) : (
        <ul className="mt-1.5 grid list-disc gap-1 ps-5 text-xs text-muted">
          {hints.map((hint) => <li key={hint}>{s.guide.hints[hint] ?? hint}</li>)}
        </ul>
      )}
    </div>
  );
}
