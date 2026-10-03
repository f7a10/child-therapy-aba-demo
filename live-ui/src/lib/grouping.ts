/**
 * Mirrors aba_demo/grouping.py: entries that happen together form one reviewable
 * moment. An entry joins the current group when it starts no later than
 * GROUP_GAP_SECONDS after the group's latest end. Kept equal by grouping.test.ts.
 */
export const GROUP_GAP_SECONDS = 1.0;

interface Groupable {
  entry_id: string;
  start_time: number;
  end_time: number;
  level: "flag" | "info";
}

export interface EntryGroup<T extends Groupable> {
  start_time: number;
  end_time: number;
  level: "flag" | "info";
  entries: T[];
}

export function groupEntries<T extends Groupable>(entries: readonly T[]): EntryGroup<T>[] {
  const ordered = [...entries].sort(
    (a, b) => a.start_time - b.start_time || (a.entry_id < b.entry_id ? -1 : a.entry_id > b.entry_id ? 1 : 0),
  );
  const groups: EntryGroup<T>[] = [];
  for (const entry of ordered) {
    const last = groups[groups.length - 1];
    if (last && entry.start_time <= last.end_time + GROUP_GAP_SECONDS + 1e-9) {
      last.entries.push(entry);
      last.end_time = Math.max(last.end_time, entry.end_time);
      if (entry.level === "flag") last.level = "flag";
    } else {
      groups.push({ start_time: entry.start_time, end_time: entry.end_time, level: entry.level, entries: [entry] });
    }
  }
  return groups;
}
