import { useState } from "react";
import { Check, CircleHelp, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useI18n } from "../lib/i18n";
import type { ClinicianMark, Verdict } from "../lib/types";
import { cx } from "./ui";

export const VERDICTS: Verdict[] = ["confirmed", "not_seen", "unsure"];

export const VERDICT_ICON: Record<Verdict, LucideIcon> = { confirmed: Check, not_seen: X, unsure: CircleHelp };

export const VERDICT_TONE: Record<Verdict, string> = {
  confirmed: "border-positive/40 bg-positive-soft text-positive",
  not_seen: "border-critical/30 bg-critical-soft text-critical",
  unsure: "border-attention-line bg-attention-soft text-attention",
};

/**
 * The therapist's own view of one moment: whether the measured change happened,
 * and a short note. Choosing the selected verdict again clears it.
 */
export function MomentReview({ mark, onMark }: {
  mark: ClinicianMark | undefined;
  onMark: (verdict: Verdict | null, note: string) => Promise<void>;
}) {
  const { s } = useI18n();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  const save = (verdict: Verdict | null, note: string) => {
    setSaving(true);
    setFailed(false);
    onMark(verdict, note).then(
      () => {
        setSaving(false);
        setEditing(false);
      },
      () => {
        setSaving(false);
        setFailed(true);
      },
    );
  };

  return (
    <div className="mt-2 grid gap-1.5">
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={s.verdict.label}>
        <span className="me-0.5 text-[11px] font-medium text-faint">{s.verdict.label}:</span>
        {VERDICTS.map((verdict) => {
          const Icon = VERDICT_ICON[verdict];
          const chosen = mark?.verdict === verdict;
          return (
            <button
              key={verdict}
              type="button"
              disabled={saving}
              aria-pressed={chosen}
              title={chosen ? s.verdict.clearHint : undefined}
              // A new verdict keeps the note; clearing the verdict drops it (a note needs a verdict).
              onClick={() => save(chosen ? null : verdict, chosen ? "" : mark?.note ?? "")}
              className={cx(
                "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium transition-colors disabled:opacity-50",
                chosen ? VERDICT_TONE[verdict] : "border-line text-muted hover:bg-surface-2 hover:text-ink",
              )}
            >
              <Icon className="size-3" aria-hidden />
              {s.verdict[verdict]}
            </button>
          );
        })}
        {mark && !editing && (
          <button
            type="button"
            onClick={() => {
              setDraft(mark.note);
              setEditing(true);
            }}
            className="text-[11px] font-medium text-accent hover:underline"
          >
            {mark.note ? s.verdict.editNote : s.verdict.addNote}
          </button>
        )}
      </div>
      {/* dir="auto": a note in the other language keeps its own reading direction. */}
      {mark?.note && !editing && <p dir="auto" className="border-s-2 border-line-strong ps-2 text-xs text-ink">{mark.note}</p>}
      {editing && mark && (
        <form
          className="grid gap-1.5"
          onSubmit={(event) => {
            event.preventDefault();
            save(mark.verdict, draft);
          }}
        >
          <textarea
            value={draft}
            maxLength={500}
            rows={2}
            autoFocus
            placeholder={s.verdict.notePlaceholder}
            onChange={(event) => setDraft(event.target.value)}
            className="w-full resize-y rounded-lg border border-line-strong bg-surface px-2.5 py-1.5 text-xs text-ink outline-none focus:border-accent"
          />
          <div className="flex gap-1.5">
            <button
              type="submit"
              disabled={saving}
              className="rounded-md bg-accent px-2.5 py-1 text-[11px] font-medium text-accent-ink disabled:opacity-50"
            >
              {s.verdict.save}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-md border border-line px-2.5 py-1 text-[11px] font-medium text-muted hover:bg-surface-2"
            >
              {s.verdict.cancel}
            </button>
          </div>
        </form>
      )}
      {failed && <p role="alert" className="text-[11px] text-critical">{s.verdict.saveError}</p>}
    </div>
  );
}
