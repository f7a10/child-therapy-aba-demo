import type { FrameBox } from "./types";

/** The boxes under a normalized point (the server applies the same rule). */
export function boxesAt(boxes: FrameBox[], x: number, y: number): FrameBox[] {
  return boxes.filter((b) => b.xyxy[0] <= x && x <= b.xyxy[2] && b.xyxy[1] <= y && y <= b.xyxy[3]);
}

/** Grid steps per box side when looking for a point only one person covers. */
const GRID = 32;
/** Clearance from other people's boxes, so rounding on the server cannot make the point ambiguous. */
const MARGIN = 0.005;

/**
 * After the therapist names which of overlapping people they meant, a point
 * inside that person's box and no one else's, as near the original click as
 * possible, so the server's one-box rule accepts it. Null when every part of
 * the box is covered by someone else.
 */
export function freePoint(boxes: FrameBox[], id: number, near: { x: number; y: number }): { x: number; y: number } | null {
  const box = boxes.find((b) => b.id === id);
  if (!box) return null;
  const [x1, y1, x2, y2] = box.xyxy;
  let best: { x: number; y: number } | null = null;
  let bestDistance = Infinity;
  for (let i = 0; i < GRID; i += 1) {
    for (let j = 0; j < GRID; j += 1) {
      const x = x1 + ((x2 - x1) * (i + 0.5)) / GRID;
      const y = y1 + ((y2 - y1) * (j + 0.5)) / GRID;
      const crowded = boxes.some((b) => b.id !== id
        && b.xyxy[0] - MARGIN <= x && x <= b.xyxy[2] + MARGIN && b.xyxy[1] - MARGIN <= y && y <= b.xyxy[3] + MARGIN);
      if (crowded) continue;
      const distance = (x - near.x) ** 2 + (y - near.y) ** 2;
      if (distance < bestDistance) {
        best = { x, y };
        bestDistance = distance;
      }
    }
  }
  return best;
}

/** Distance between a person box and a drawn area, in box heights (0 when they touch). Mirrors aba_demo area_gap. */
export function areaGap(box: [number, number, number, number], region: [number, number, number, number]): number {
  const dx = Math.max(region[0] - box[2], box[0] - region[2], 0);
  const dy = Math.max(region[1] - box[3], box[1] - region[3], 0);
  return Math.hypot(dx, dy) / Math.max(box[3] - box[1], 1e-9);
}

/** Within this distance the child counts as at the work area (aba_demo AREA_NEAR_MAX). */
export const AREA_NEAR_MAX = 0.05;
