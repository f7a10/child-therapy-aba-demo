import { describe, expect, it } from "vitest";
import { boxesAt, freePoint } from "./selection";
import type { FrameBox } from "./types";

const box = (id: number, xyxy: [number, number, number, number]) => ({ id, xyxy }) as FrameBox;

describe("freePoint", () => {
  // An adult whose box covers most of the child's, as when the adult sits in front.
  const boxes = [box(1, [0.0, 0.2, 0.9, 1.0]), box(2, [0.5, 0.3, 0.98, 0.7])];

  it("finds a point only the chosen person covers, near the click", () => {
    const point = freePoint(boxes, 2, { x: 0.7, y: 0.5 })!;
    expect(boxesAt(boxes, point.x, point.y).map((b) => b.id)).toEqual([2]);
    expect(point.x).toBeGreaterThan(0.9);
    expect(Math.abs(point.y - 0.5)).toBeLessThan(0.02);
  });

  it("works for the outer person too", () => {
    const point = freePoint(boxes, 1, { x: 0.7, y: 0.5 })!;
    expect(boxesAt(boxes, point.x, point.y).map((b) => b.id)).toEqual([1]);
  });

  it("is null when the person is wholly covered or unknown", () => {
    const covered = [box(1, [0, 0, 1, 1]), box(2, [0.2, 0.2, 0.4, 0.4])];
    expect(freePoint(covered, 2, { x: 0.3, y: 0.3 })).toBeNull();
    expect(freePoint(covered, 9, { x: 0.3, y: 0.3 })).toBeNull();
  });
});
