import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { readFileSync } from "node:fs";
import type { IdfData, ReplayData } from "../layers/convectionIdf";
import type { ConvectionState } from "../layers/useConvectionIdf";
import { ConvectionPanel } from "./ConvectionPanel";
import { RainLegend } from "./RainLegend";

const dir = "e2e/fixtures/processed/convection-idf/";
const idf = JSON.parse(readFileSync(dir + "idf.json", "utf8")) as IdfData;
const replay = JSON.parse(readFileSync(dir + "replay.json", "utf8")) as ReplayData;

const state = (over: Partial<ConvectionState> = {}): ConvectionState =>
  ({
    status: "ready", idf, replay, nFrames: 12, frame: 0, playing: false,
    cursorMs: Date.parse("2014-04-06T10:00:00Z"), toggle: vi.fn(), step: vi.fn(), seek: vi.fn(), deckLayers: [], ...over,
  }) as ConvectionState; // fmt: skip

test("IDF chart draws one curve per return period, the baseline and marks the extrapolation", () => {
  render(<ConvectionPanel state={state()} source="Fuente X" period="2000-07-01/2025-06-30" />);
  expect(screen.getAllByTestId(/^idf-curve-/)).toHaveLength(6);
  expect(screen.getAllByTestId(/^idf-gumbel-/)).toHaveLength(6);
  expect(screen.getByTestId("idf-curve-100")).toHaveAttribute("data-extrapolated", "true");
  expect(screen.getByTestId("idf-curve-50")).toHaveAttribute("data-extrapolated", "false");
  expect(screen.getByTestId("idf-label-100")).toHaveTextContent("T 100†");
  expect(screen.getByTestId("idf-label")).toHaveTextContent("IDF solo con IMERG, sin corrección de sesgo");
  expect(screen.getByTestId("idf-source")).toHaveTextContent("Fuente X");
  expect(screen.getByTestId("conv-not-alert")).toHaveTextContent("No es un sistema de alerta oficial");
});

test("scenarios toggle and the selected return period move the band", () => {
  render(<ConvectionPanel state={state()} source="s" period="p" />);
  expect(screen.queryAllByTestId(/^idf-scenario-/)).toHaveLength(0);
  fireEvent.click(screen.getByTestId("idf-scenarios"));
  expect(screen.getAllByTestId(/^idf-scenario-/)).toHaveLength(2);
  expect(screen.getByTestId("idf-band")).toHaveAttribute("data-t", "10");
  fireEvent.click(screen.getByTestId("idf-t-5"));
  expect(screen.getByTestId("idf-band")).toHaveAttribute("data-t", "5");
  expect(screen.getByTestId("idf-t-100")).toHaveTextContent("T 100†");
});

test("comparison shows the station value, IMERG, the ratio and the cumulative at the frame", () => {
  const { rerender } = render(<ConvectionPanel state={state()} source="s" period="p" />);
  expect(screen.getByTestId("compare-station")).toHaveTextContent("118 mm");
  expect(screen.getByTestId("compare-imerg")).toHaveTextContent("97,6 mm");
  expect(screen.getByTestId("compare-ratio")).toHaveTextContent("0,83");
  expect(screen.getByTestId("compare-current")).toHaveTextContent("antes de la ventana");
  rerender(<ConvectionPanel state={state({ frame: 8, cursorMs: Date.parse("2014-04-06T14:00:00Z") })} source="s" period="p" />);
  expect(screen.getByTestId("compare-current")).toHaveTextContent("97,6 mm");
});

test("replay controls call the state", () => {
  const s = state();
  render(<ConvectionPanel state={s} source="s" period="p" />);
  fireEvent.click(screen.getByTestId("rain-play"));
  expect(s.toggle).toHaveBeenCalled();
  fireEvent.click(screen.getByTestId("rain-forward"));
  expect(s.step).toHaveBeenCalledWith(1);
  fireEvent.change(screen.getByTestId("rain-slider"), { target: { value: "5" } });
  expect(s.seek).toHaveBeenCalledWith(5);
  expect(screen.getByTestId("rain-time")).toHaveTextContent("2014-04-06 10:00 UTC");
});

test("loading and error states", () => {
  const { rerender } = render(<ConvectionPanel state={state({ status: "loading", idf: null, replay: null })} source="s" period="p" />);
  expect(screen.getByText(/Cargando/)).toBeInTheDocument();
  rerender(<ConvectionPanel state={state({ status: "error", idf: null, replay: null })} source="s" period="p" />);
  expect(screen.getByText(/No se pudo cargar/)).toBeInTheDocument();
});

test("rain legend shows source, ticks and the clock", () => {
  render(<RainLegend source="IMERG X" cursorMs={Date.parse("2014-04-06T10:00:00Z")} />);
  expect(screen.getByTestId("rain-legend")).toHaveTextContent("Fuente: IMERG X");
  expect(screen.getByTestId("rain-legend-ticks")).toHaveTextContent("0138≥20");
  expect(screen.getByTestId("rain-clock")).toHaveTextContent("2014-04-06 10:00 UTC");
});
