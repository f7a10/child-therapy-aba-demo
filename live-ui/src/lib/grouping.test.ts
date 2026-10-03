import { describe, expect, it } from "vitest";
import { GROUP_GAP_SECONDS, groupEntries } from "./grouping";

const item = (entry_id: string, start_time: number, end_time: number, level: "flag" | "info" = "info") =>
  ({ entry_id, start_time, end_time, level });

describe("grouping", () => {
  it("matches aba_demo.grouping (tests/test_grouping.py)", () => {
    expect(GROUP_GAP_SECONDS).toBe(1.0);
    const groups = groupEntries([item("stood", 148.2, 148.6, "flag"), item("moved", 148.0, 151.4),
      item("sat", 31.4, 31.6), item("note", 31.4, 31.6), item("later", 152.3, 152.7), item("far", 154.0, 154.2)]);
    expect(groups.map((g) => g.entries.map((e) => e.entry_id))).toEqual([["note", "sat"], ["moved", "stood", "later"], ["far"]]);
    expect(groups.map((g) => g.level)).toEqual(["info", "flag", "info"]);
    expect(groups.map((g) => [g.start_time, g.end_time])).toEqual([[31.4, 31.6], [148, 152.7], [154, 154.2]]);
    expect(groupEntries([])).toEqual([]);
  });
});
