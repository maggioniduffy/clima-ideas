import { fireEvent, render, screen } from "@testing-library/react";
import { BACKGROUND_KEY, MapBackground, parseBackground, readBackground, writeBackground } from "./MapBackground";

afterEach(() => localStorage.clear());

test("invalid or missing stored values fall back to Ambos", () => {
  expect(parseBackground("nope")).toBe("both");
  expect(readBackground()).toBe("both");
  localStorage.setItem(BACKGROUND_KEY, "basemap");
  expect(readBackground()).toBe("basemap");
  localStorage.setItem(BACKGROUND_KEY, "junk");
  expect(readBackground()).toBe("both");
});

test("writeBackground persists under map-background", () => {
  writeBackground("relief");
  expect(localStorage.getItem("map-background")).toBe("relief");
});

test("the control marks the current mode and reports changes", () => {
  const onChange = vi.fn();
  render(<MapBackground value="both" onChange={onChange} />);
  expect(screen.getByTestId("map-bg-both")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("map-bg-relief")).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(screen.getByTestId("map-bg-basemap"));
  expect(onChange).toHaveBeenCalledWith("basemap");
});
