import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { readFileSync } from "node:fs";
import { rankCatchments, type CatchmentCollection, type DebrisPeaks } from "../layers/debrisCatchments";
import type { DebrisState } from "../layers/useDebrisCatchments";
import { DebrisLegend } from "./DebrisLegend";
import { DebrisPanel } from "./DebrisPanel";

const dir = "e2e/fixtures/processed/debris-catchments/";
const geo = JSON.parse(readFileSync(dir + "catchments.geojson", "utf8")) as CatchmentCollection;
const peaks = JSON.parse(readFileSync(dir + "peaks.json", "utf8")) as DebrisPeaks;

const state = (over: Partial<DebrisState> = {}): DebrisState => {
  const ranking = rankCatchments(geo.features, peaks, "hsg-c", 10);
  return {
    status: "ready", peaks, geo, t: 10, cnId: "hsg-c", selectedId: null, selected: null, ranking, top: ranking,
    domain: [0.7, 9], setT: vi.fn(), setCnId: vi.fn(), select: vi.fn(), deckLayers: [], selectedPeak: null, ...over,
  } as unknown as DebrisState;
};

test("ranked list, selectors and fixed caveats are shown without a selection", () => {
  render(<DebrisPanel state={state()} source="Fuente X" period="2000-07-01/2025-06-30" />);
  expect(screen.getAllByTestId(/^debris-rank-\d+$/)).toHaveLength(4);
  expect(screen.getByTestId("debris-rank-0")).toHaveTextContent("1. RP5");
  expect(screen.getByTestId("debris-empty")).toBeInTheDocument();
  expect(screen.getByTestId("debris-t-100")).toHaveTextContent("T 100†");
  expect(screen.getByTestId("debris-cn-hsg-c")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("debris-scenario-label")).toHaveTextContent("Escenarios de CN (TR-55), no medidos");
  const caveats = screen.getByTestId("debris-caveats");
  for (const txt of ["piso de IMERG", "sin verificar", "TR-55", "bardas patagónicas", "No es un sistema de alerta oficial"])
    expect(caveats).toHaveTextContent(txt);
  expect(screen.getByTestId("debris-source")).toHaveTextContent("Fuente X");
  expect(screen.getByTestId("debris-source")).toHaveTextContent("2000/01");
});

test("clicking a ranked row, T and CN buttons call back", () => {
  const s = state();
  render(<DebrisPanel state={s} source="s" period="p" />);
  fireEvent.click(screen.getByTestId("debris-rank-2"));
  expect(s.select).toHaveBeenCalledWith(2);
  fireEvent.click(screen.getByTestId("debris-t-50"));
  expect(s.setT).toHaveBeenCalledWith(50);
  fireEvent.click(screen.getByTestId("debris-cn-hsg-d"));
  expect(s.setCnId).toHaveBeenCalledWith("hsg-d");
});

test("selected catchment: properties, one peak row per T with the CN range and critical duration", () => {
  const selected = geo.features[0]!.properties;
  render(<DebrisPanel state={state({ selectedId: 0, selected })} source="s" period="p" />);
  expect(screen.getByTestId("debris-target")).toHaveTextContent("RP5");
  expect(screen.getByTestId("debris-area")).toHaveTextContent("12 km²");
  expect(screen.getByTestId("debris-slope")).toHaveTextContent("3,5°");
  expect(screen.getByTestId("debris-flowpath")).toHaveTextContent("9.000 m");
  expect(screen.getAllByTestId(/^debris-peak-row-/)).toHaveLength(6);
  expect(screen.getByTestId("debris-peak-10")).toHaveTextContent("9,14");
  expect(screen.getByTestId("debris-range-10").textContent).toMatch(/^[\d,]+–[\d,]+$/);
  expect(screen.getByTestId("debris-crit-10").textContent).toMatch(/h$|min$/);
  expect(screen.getByTestId("debris-peak-row-10")).toHaveAttribute("data-current", "true");
  expect(screen.getByTestId("debris-peak-row-100")).toHaveTextContent("T 100†");
});

test("legend shows the log-scale limits and source", () => {
  render(<DebrisLegend domain={[0.7, 9]} source="Fuente Y" />);
  expect(screen.getByTestId("debris-legend-ticks")).toHaveTextContent("0,7");
  expect(screen.getByTestId("debris-legend")).toHaveTextContent("Fuente: Fuente Y");
});
