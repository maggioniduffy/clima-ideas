import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { stepSize } from "./panelSizes";

interface Props {
  className: string;
  orientation: "vertical" | "horizontal";
  /** +1 when dragging toward the end of the axis (right/down) grows the panel, -1 when it shrinks it. */
  dir: 1 | -1;
  /** Current size; 0 when the panel is collapsed. */
  value: number;
  /** Smallest visible size: dragging below it collapses the panel. */
  min: number;
  max: number;
  defaultValue: number;
  label: string;
  testId: string;
  onChange: (value: number) => void;
}

/** Draggable/keyboard separator in the gap next to a panel; it can collapse the panel to 0 and bring it back. */
export function PanelResizer({ className, orientation, dir, value, min, max, defaultValue, label, testId, onChange }: Props) {
  const [dragging, setDragging] = useState(false);
  const start = useRef({ pos: 0, value: 0 });
  const axis = (e: PointerEvent) => (orientation === "vertical" ? e.clientX : e.clientY);
  /** Pointer-driven size: below the minimum snaps to 0; leaving the collapsed state shows the panel from its minimum upward. */
  const dragSize = (raw: number) => {
    const v = Math.round(raw);
    if (start.current.value === 0) return v > 0 ? Math.min(max, Math.max(min, v)) : 0;
    return v < min ? 0 : Math.min(max, v);
  };

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    start.current = { pos: axis(e), value };
    setDragging(true);
    document.body.style.userSelect = "none";
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    onChange(dragSize(start.current.value + (axis(e) - start.current.pos) * dir));
  };
  const endDrag = (e: PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    setDragging(false);
    document.body.style.userSelect = "";
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const next = stepSize(e.key, orientation, dir, value, min, max, defaultValue);
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
      data-collapsed={value === 0 || undefined}
      aria-orientation={orientation}
      aria-label={label}
      aria-valuenow={value}
      aria-valuemin={0}
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
