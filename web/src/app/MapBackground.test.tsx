import { fireEvent, render, screen } from "@testing-library/react";
import {
  BACKGROUND_KEY,
  DEFAULT_BACKGROUND,
  effectiveBackground,
  MapBackground,
  parseBackground,
  readBackground,
  reliefVisible,
  writeBackground,
} from "./MapBackground";

afterEach(() => localStorage.clear());

test("the default background is the relief; invalid or missing stored values fall back to it", () => {
  expect(DEFAULT_BACKGROUND).toBe("relief");
  expect(parseBackground("nope")).toBe("relief");
  expect(readBackground()).toBe("relief");
  localStorage.setItem(BACKGROUND_KEY, "basemap");
  expect(readBackground()).toBe("basemap");
  localStorage.setItem(BACKGROUND_KEY, "junk");
  expect(readBackground()).toBe("relief");
});

test("writeBackground persists under map-background", () => {
  writeBackground("both");
  expect(localStorage.getItem("map-background")).toBe("both");
});

test("effective mode: no basemap means relief or none; with a basemap none does not exist", () => {
  expect(effectiveBackground("both", false)).toBe("relief");
  expect(effectiveBackground("basemap", false)).toBe("relief");
  expect(effectiveBackground("none", false)).toBe("none");
  expect(effectiveBackground("none", true)).toBe("relief");
  expect(effectiveBackground("basemap", true)).toBe("basemap");
});

test("the relief is drawn in relief and both only", () => {
  expect(["relief", "both", "basemap", "none"].map((m) => reliefVisible(m as never))).toEqual([true, true, false, false]);
});

test("the control marks the current mode and reports changes", () => {
  const onChange = vi.fn();
  render(<MapBackground value="both" onChange={onChange} />);
  expect(screen.getByTestId("map-bg-both")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("map-bg-relief")).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(screen.getByTestId("map-bg-basemap"));
  expect(onChange).toHaveBeenCalledWith("basemap");
});

test("without a basemap the control offers relief on / off only", () => {
  const onChange = vi.fn();
  render(<MapBackground value="relief" onChange={onChange} hasBasemap={false} />);
  expect(screen.queryByTestId("map-bg-basemap")).toBeNull();
  expect(screen.queryByTestId("map-bg-both")).toBeNull();
  expect(screen.getByTestId("map-bg-relief")).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByTestId("map-bg-none"));
  expect(onChange).toHaveBeenCalledWith("none");
});
