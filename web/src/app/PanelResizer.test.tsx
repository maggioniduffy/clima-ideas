import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { PanelResizer } from "./PanelResizer";

// jsdom has no PointerEvent: a MouseEvent with a pointer type carries clientX/clientY
const ptr = (el: Element, type: string, x: number) =>
  fireEvent(el, new MouseEvent(type, { bubbles: true, button: 0, clientX: x }));

function setup(dir: 1 | -1 = 1, orientation: "vertical" | "horizontal" = "vertical", value = 200) {
  const onChange = vi.fn();
  render(
    <PanelResizer
      className="x"
      orientation={orientation}
      dir={dir}
      value={value}
      min={160}
      max={480}
      defaultValue={240}
      label="Ancho"
      testId="r"
      onChange={onChange}
    />,
  );
  return { sep: screen.getByRole("separator", { name: "Ancho" }), onChange };
}

test("exposes separator semantics", () => {
  const { sep } = setup();
  expect(sep).toHaveAttribute("aria-orientation", "vertical");
  expect(sep).toHaveAttribute("aria-valuenow", "200");
  expect(sep).toHaveAttribute("aria-valuemin", "0");
  expect(sep).toHaveAttribute("aria-valuemax", "480");
  expect(sep).toHaveAttribute("tabindex", "0");
});

test("arrow keys move 16 px, Home/End jump to the limits", () => {
  const { sep, onChange } = setup();
  fireEvent.keyDown(sep, { key: "ArrowRight" });
  expect(onChange).toHaveBeenLastCalledWith(216);
  fireEvent.keyDown(sep, { key: "ArrowLeft" });
  expect(onChange).toHaveBeenLastCalledWith(184);
  fireEvent.keyDown(sep, { key: "End" });
  expect(onChange).toHaveBeenLastCalledWith(480);
});

test("Home collapses to 0, Enter restores the default", () => {
  const { sep, onChange } = setup();
  fireEvent.keyDown(sep, { key: "Home" });
  expect(onChange).toHaveBeenLastCalledWith(0);
  fireEvent.keyDown(sep, { key: "Enter" });
  expect(onChange).toHaveBeenLastCalledWith(240);
});

test("a collapsed handle reports 0 and arrows bring the panel back at its minimum", () => {
  const { sep, onChange } = setup(1, "vertical", 0);
  expect(sep).toHaveAttribute("aria-valuenow", "0");
  fireEvent.keyDown(sep, { key: "ArrowRight" });
  expect(onChange).toHaveBeenLastCalledWith(160);
});

test("inverted axis: ArrowLeft grows an inspector-like panel; timeline uses Up/Down", () => {
  const a = setup(-1);
  fireEvent.keyDown(a.sep, { key: "ArrowLeft" });
  expect(a.onChange).toHaveBeenLastCalledWith(216);
  cleanup();
  const b = setup(-1, "horizontal");
  fireEvent.keyDown(b.sep, { key: "ArrowUp" });
  expect(b.onChange).toHaveBeenLastCalledWith(216);
});

test("double click resets to the default", () => {
  const { sep, onChange } = setup();
  fireEvent.doubleClick(sep);
  expect(onChange).toHaveBeenCalledWith(240);
});

test("pointer drag follows the pointer, clamped to the limits", () => {
  const { sep, onChange } = setup();
  ptr(sep, "pointerdown", 100);
  ptr(sep, "pointermove", 150);
  expect(onChange).toHaveBeenLastCalledWith(250);
  ptr(sep, "pointermove", 900);
  expect(onChange).toHaveBeenLastCalledWith(480);
  ptr(sep, "pointerup", 900);
  onChange.mockClear();
  ptr(sep, "pointermove", 120);
  expect(onChange).not.toHaveBeenCalled();
});

test("dragging below the minimum snaps to 0 and dragging back out restores from the minimum upward", () => {
  const { sep, onChange } = setup();
  ptr(sep, "pointerdown", 100);
  ptr(sep, "pointermove", 50); // 200 - 50 = 150 < 160
  expect(onChange).toHaveBeenLastCalledWith(0);
  ptr(sep, "pointermove", 60); // 160
  expect(onChange).toHaveBeenLastCalledWith(160);
  ptr(sep, "pointermove", 0);
  expect(onChange).toHaveBeenLastCalledWith(0);
  ptr(sep, "pointerup", 0);
});

test("dragging out of the collapsed state shows the panel at its minimum and follows the pointer", () => {
  const { sep, onChange } = setup(1, "vertical", 0);
  ptr(sep, "pointerdown", 8);
  ptr(sep, "pointermove", 4);
  expect(onChange).toHaveBeenLastCalledWith(0);
  ptr(sep, "pointermove", 12); // 4 px out: still below the minimum, shown at the minimum
  expect(onChange).toHaveBeenLastCalledWith(160);
  ptr(sep, "pointermove", 208);
  expect(onChange).toHaveBeenLastCalledWith(200);
});
