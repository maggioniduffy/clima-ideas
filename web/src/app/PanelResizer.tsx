import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { stepSize } from "./panelSizes";

interface Props {
  className: string;
  orientation: "vertical" | "horizontal";
  /** +1 when dragging toward the end of the axis (right/down) grows the panel, -1 when it shrinks it. */
  dir: 1 | -1;
  value: number;
  min: number;
  max: number;
  defaultValue: number;
  label: string;
  testId: string;
  onChange: (value: number) => void;
}

/** Thin draggable/keyboard separator on a panel's inner edge. */
export function PanelResizer({ className, orientation, dir, value, min, max, defaultValue, label, testId, onChange }: Props) {
  const [dragging, setDragging] = useState(false);
  const start = useRef({ pos: 0, value: 0 });
  const axis = (e: PointerEvent) => (orientation === "vertical" ? e.clientX : e.clientY);
  const clamp = (v: number) => Math.min(max, Math.max(min, Math.round(v)));

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    start.current = { pos: axis(e), value };
    setDragging(true);
    document.body.style.userSelect = "none";
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    onChange(clamp(start.current.value + (axis(e) - start.current.pos) * dir));
  };
  const endDrag = (e: PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    setDragging(false);
    document.body.style.userSelect = "";
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const next = stepSize(e.key, orientation, dir, value, min, max);
    if (next == null) return;
    e.preventDefault();
    onChange(next);
  };

  return (
    <div
      role="separator"
      tabIndex={0}
      className={className}
      data-testid={testId}
      data-dragging={dragging || undefined}
      aria-orientation={orientation}
      aria-label={label}
      aria-valuenow={value}
      aria-valuemin={min}
      aria-valuemax={max}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={onKeyDown}
      onDoubleClick={() => onChange(defaultValue)}
    />
  );
}
