import { useRef, useState } from "react";
import type { PointerEvent } from "react";
import type { FrameBox } from "../lib/types";
import { cx } from "./ui";

export type Region = [number, number, number, number];
export interface Click {
  x: number;
  y: number;
  boxId: number;
}

/** The boxes under a normalized point (the server applies the same rule). */
export function boxesAt(boxes: FrameBox[], x: number, y: number): FrameBox[] {
  return boxes.filter((b) => b.xyxy[0] <= x && x <= b.xyxy[2] && b.xyxy[1] <= y && y <= b.xyxy[3]);
}

/**
 * One analysis frame with every tracked person boxed. A click inside exactly one
 * box chooses that person; in drawing mode a drag draws the task area instead.
 * Image coordinates always run left to right, whatever the reading direction.
 */
export function FramePicker({ src, width, height, boxes, click, onClick, drawing, region, onRegion, alt }: {
  src: string;
  width: number;
  height: number;
  boxes: FrameBox[];
  click: Click | null;
  onClick: (x: number, y: number) => void;
  drawing: boolean;
  region: Region | null;
  onRegion: (region: Region) => void;
  alt: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ x: number; y: number; x2: number; y2: number } | null>(null);

  const point = (event: PointerEvent) => {
    const rect = ref.current!.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
      y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
    };
  };

  const onDown = (event: PointerEvent) => {
    const p = point(event);
    if (!drawing) {
      onClick(p.x, p.y);
      return;
    }
    (event.target as Element).setPointerCapture?.(event.pointerId);
    setDrag({ x: p.x, y: p.y, x2: p.x, y2: p.y });
  };
  const onMove = (event: PointerEvent) => {
    if (!drag) return;
    const p = point(event);
    setDrag({ ...drag, x2: p.x, y2: p.y });
  };
  const onUp = () => {
    if (!drag) return;
    const next: Region = [Math.min(drag.x, drag.x2), Math.min(drag.y, drag.y2), Math.max(drag.x, drag.x2), Math.max(drag.y, drag.y2)];
    setDrag(null);
    if (next[2] - next[0] > 0.02 && next[3] - next[1] > 0.02) onRegion(next);
  };

  const shown: Region | null = drag
    ? [Math.min(drag.x, drag.x2), Math.min(drag.y, drag.y2), Math.max(drag.x, drag.x2), Math.max(drag.y, drag.y2)]
    : region;
  const style = (r: readonly [number, number, number, number]) => ({
    left: `${r[0] * 100}%`,
    top: `${r[1] * 100}%`,
    width: `${(r[2] - r[0]) * 100}%`,
    height: `${(r[3] - r[1]) * 100}%`,
  });

  return (
    <div
      ref={ref}
      dir="ltr"
      className={cx("relative w-full touch-none select-none overflow-hidden rounded-xl bg-black", drawing ? "cursor-crosshair" : "cursor-pointer")}
      style={{ aspectRatio: `${width} / ${height}` }}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
    >
      <img src={src} alt={alt} className="absolute inset-0 size-full object-contain" draggable={false} />
      {boxes.map((box) => {
        const chosen = click?.boxId === box.id;
        return (
          <span
            key={box.id}
            className={cx(
              "pointer-events-none absolute rounded-sm border-2 transition-colors",
              chosen ? "border-positive bg-positive/15 shadow-[0_0_0_2px_rgb(0_0_0/0.35)]" : "border-white/80 bg-white/5",
            )}
            style={style(box.xyxy)}
          />
        );
      })}
      {shown && (
        <span className="pointer-events-none absolute rounded-sm border-2 border-dashed border-sky-400 bg-sky-400/10" style={style(shown)} />
      )}
      {click && (
        <span
          className="pointer-events-none absolute size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-positive"
          style={{ left: `${click.x * 100}%`, top: `${click.y * 100}%` }}
        />
      )}
    </div>
  );
}
