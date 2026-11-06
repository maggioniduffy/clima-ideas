import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { es } from "../i18n/es";
import { Shell } from "./Shell";

vi.mock("@deck.gl/react", () => ({
  default: () => <div data-testid="deck-mock" />,
}));

const manifest = {
  id: "a",
  title: "Capa A",
  kind: "points",
  source: "Fuente X",
  period: "2000-01-01/2000-12-31",
  license: "CC0",
  updated_at: "2026-01-01T00:00:00Z",
  files: ["p.json"],
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => (url.endsWith("/data") ? [{ id: "p1", lon: -69, lat: -38, value: 5.5 }] : [manifest]),
    })),
  );
});
afterEach(() => vi.unstubAllGlobals());

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

test("activating a fetched layer adds the deck layer and shows manifest source/period", async () => {
  render(<Shell />);
  fireEvent.click(await screen.findByTestId("layer-toggle-a"));
  await waitFor(() => expect(screen.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", "points-a"));
  expect(screen.getByTestId("layer-item-a")).toHaveAttribute("data-active", "true");
  expect(screen.getByTestId("inspector-source")).toHaveTextContent("Fuente X");
  expect(screen.getByTestId("inspector-period")).toHaveTextContent("2000-01-01/2000-12-31");
  fireEvent.click(screen.getByTestId("feature-p1"));
  expect(screen.getByTestId("inspector-point")).toHaveTextContent("5.5");
  fireEvent.click(screen.getByTestId("layer-toggle-a"));
  expect(screen.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", "");
});
