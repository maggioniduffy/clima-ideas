import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { PanelResizer } from "./PanelResizer";

// jsdom has no PointerEvent: a MouseEvent with a pointer type carries clientX/clientY
const ptr = (el: Element, type: string, x: number) =>
  fireEvent(el, new MouseEvent(type, { bubbles: true, button: 0, clientX: x }));

function setup(dir: 1 | -1 = 1, orientation: "vertical" | "horizontal" = "vertical") {
  const onChange = vi.fn();
  render(
    <PanelResizer
      className="x"
      orientation={orientation}
      dir={dir}
      value={200}
      min={160}
      max={480}
      defaultValue={200}
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
  expect(sep).toHaveAttribute("aria-valuemin", "160");
  expect(sep).toHaveAttribute("aria-valuemax", "480");
  expect(sep).toHaveAttribute("tabindex", "0");
});

test("arrow keys move 16 px, Home/End jump to the limits", () => {
  const { sep, onChange } = setup();
  fireEvent.keyDown(sep, { key: "ArrowRight" });
  expect(onChange).toHaveBeenLastCalledWith(216);
  fireEvent.keyDown(sep, { key: "ArrowLeft" });
  expect(onChange).toHaveBeenLastCalledWith(184);
  fireEvent.keyDown(sep, { key: "Home" });
  expect(onChange).toHaveBeenLastCalledWith(160);
  fireEvent.keyDown(sep, { key: "End" });
  expect(onChange).toHaveBeenLastCalledWith(480);
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
  expect(onChange).toHaveBeenCalledWith(200);
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
