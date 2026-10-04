import { describe, expect, it } from "vitest";
import { STRINGS, contextDetails, readStoredLanguage, timelineText } from "./i18n";

function shape(value: unknown): unknown {
  if (typeof value === "function") return "fn";
  if (Array.isArray(value)) return value.map(shape);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, shape((value as Record<string, unknown>)[key])]));
  }
  return typeof value;
}

describe("i18n", () => {
  it("has the same keys in English and Arabic", () => {
    expect(shape(STRINGS.ar)).toEqual(shape(STRINGS.en));
    expect(STRINGS.en.dir).toBe("ltr");
    expect(STRINGS.ar.dir).toBe("rtl");
  });

  it("renders log items in the chosen language", () => {
    const item = { label: { type: "identity" as const, identity: "uncertain" as const } };
    expect(timelineText(item, STRINGS.en).title).toBe("Identity uncertain");
    expect(timelineText(item, STRINGS.ar).title).toBe("هوية الطفل غير مؤكدة");
    const flag = { label: { type: "flag" as const, kind: "sit_to_stand" } };
    expect(timelineText(flag, STRINGS.ar).title).toBe("قام من الجلوس — للمراجعة");
    const unknown = { label: { type: "error" as const, code: "new_failure_code" } };
    expect(timelineText(unknown, STRINGS.en).title).toBe("New failure code");
  });

  it("renders closed-enum context notes in both languages", () => {
    const note = { child_separable: "yes", child_location: "walking", child_handling_material: "no" };
    expect(contextDetails(note, STRINGS.en)).toBe("moving around · not holding material");
    expect(contextDetails(note, STRINGS.ar)).toBe("يتنقّل · لا يمسك أداة");
    expect(contextDetails({ child_separable: "no" }, STRINGS.ar)).toBe("تعذّر فصل جسم الطفل عن البالغ");
    expect(contextDetails({ child_separable: "yes", child_location: "not_observable" }, STRINGS.en)).toBe("");
  });

  it("falls back to English when storage is unavailable or holds junk", () => {
    expect(readStoredLanguage({ getItem: () => "ar" })).toBe("ar");
    expect(readStoredLanguage({ getItem: () => "fr" })).toBe("en");
    expect(readStoredLanguage({ getItem: () => { throw new Error("blocked"); } })).toBe("en");
    expect(readStoredLanguage(null)).toBe("en");
  });
});

describe("context v2 notes", () => {
  it("tell before, the model's view and after; material changes only when reported", async () => {
    const { STRINGS, contextStory } = await import("./i18n");
    const s = STRINGS.ar;
    expect(contextStory({ child_separable: "yes", child_location: "at_table" }, s)).toBeNull();
    const story = contextStory(
      {
        child_separable: "yes",
        child_position_after: "standing",
        adult_movement_before: "moved_closer",
        adult_movement_after: "stayed",
        materials_change_before: "no_change",
        materials_change_after: "removed",
        second_opinion: "disagrees",
      },
      s,
    );
    expect(story).toEqual({
      positionBefore: "",
      before: "البالغ اقترب",
      after: "البالغ بقي في مكانه",
      position: "واقف",
      opinion: "disagrees",
      experimental: { before: "", after: "أُزيلت أدوات" },
    });
    const hidden = contextStory({ child_separable: "no", second_opinion: "unclear" }, STRINGS.en);
    expect(hidden?.position).toBe(STRINGS.en.detail.notSeparable);
    expect(hidden?.opinion).toBeNull();
  });
});
