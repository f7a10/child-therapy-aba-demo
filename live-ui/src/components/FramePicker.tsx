import { useRef, useState } from "react";
import type { PointerEvent } from "react";
import { boxesAt } from "../lib/selection";
import type { FrameBox } from "../lib/types";
import { cx } from "./ui";

export { boxesAt };

export type Region = [number, number, number, number];
export interface Click {
  x: number;
  y: number;
  boxId: number;
}

/**
 * One analysis frame with every tracked person boxed. A click inside exactly one
 * box chooses that person; in drawing mode a drag draws the task area instead.
 * Image coordinates always run left to right, whatever the reading direction.
 */
export function FramePicker({ src, width, height, boxes, click, onClick, drawing, region, onRegion, alt, candidates = [], focus = null }: {
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
  /** After a click on overlapping people: their boxes, numbered so the therapist can name one. */
  candidates?: number[];
  focus?: number | null;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ x: number; y: number; x2: number; y2: number } | null>(null);
  // The one box under the pointer, outlined so the therapist sees what a click would choose.
  const [hover, setHover] = useState<number | null>(null);

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
    const p = point(event);
    if (!drag) {
      const hits = drawing ? [] : boxesAt(boxes, p.x, p.y);
      setHover(hits.length === 1 ? hits[0]!.id : null);
      return;
    }
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
      className={cx("relative mx-auto touch-none select-none overflow-hidden rounded-xl bg-black", drawing ? "cursor-crosshair" : "cursor-pointer")}
      // Tall (phone) videos are limited to the window height instead of filling the width.
      style={{ aspectRatio: `${width} / ${height}`, width: `min(100%, calc(72dvh * ${width / height}))` }}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerLeave={() => setHover(null)}
    >
      <img src={src} alt={alt} className="absolute inset-0 size-full object-contain" draggable={false} />
      {boxes.map((box) => {
        const chosen = click?.boxId === box.id;
        const candidate = candidates.indexOf(box.id);
        const hovered = !chosen && (focus === box.id || (focus === null && hover === box.id));
        return (
          <span
            key={box.id}
            className={cx(
              "pointer-events-none absolute rounded-sm border-2 transition-colors",
              chosen
                ? "border-positive bg-positive/15 shadow-[0_0_0_2px_rgb(0_0_0/0.35)]"
                : hovered
                  ? "border-[#f2c979] bg-[#f2c979]/15 shadow-[0_0_0_2px_rgb(0_0_0/0.35)]"
                  : "border-white/85 bg-white/5 shadow-[0_0_0_1px_rgb(0_0_0/0.45)]",
            )}
            style={style(box.xyxy)}
          >
            {candidate >= 0 && (
              <span className="absolute top-1 left-1 grid size-6 place-items-center rounded-full bg-[#f2c979] text-xs font-bold text-black shadow">
                {candidate + 1}
              </span>
            )}
          </span>
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
