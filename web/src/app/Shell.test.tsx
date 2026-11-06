import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { es } from "../i18n/es";
import { Shell } from "./Shell";

vi.mock("@deck.gl/react", () => ({
  default: () => <div data-testid="deck-mock" />,
}));

const regions = ["topbar", "layer-panel", "map-canvas", "inspector", "timeline"];

test("Shell renders the five regions", () => {
  render(<Shell />);
  for (const id of regions) expect(screen.getByTestId(id)).toBeInTheDocument();
  expect(screen.getByTestId("deck-mock")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: es.appTitle })).toBeInTheDocument();
});

test("theme toggle in the top bar flips data-theme", () => {
  render(<Shell />);
  const before = document.documentElement.dataset.theme;
  fireEvent.click(screen.getByRole("button", { name: es.theme.toggle }));
  expect(document.documentElement.dataset.theme).not.toBe(before);
  fireEvent.click(screen.getByRole("button", { name: es.theme.toggle }));
  expect(document.documentElement.dataset.theme).toBe(before);
});
