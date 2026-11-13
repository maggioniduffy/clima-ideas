import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Layer } from "@deck.gl/core";
import { fetchFrames, fetchLayerBinary, fetchLayerData, type ArEvent, type FramesIndex, type LayerManifest } from "../api/client";
import { useTheme } from "../theme/themeStore";
import { frameTime, frameValue, gridCells, parseFrames, type IvtView } from "./arEvents";
import { DEFAULT_TOGGLES, filterEvents, type ArToggles } from "./arFilter";
import { coreLevel, countReaching, footprintOf, parseFootprints, type Footprints } from "./arFootprint";
import { buildIvtContourLayers } from "./ivtContours";
import { buildCountLayer, buildIvtRasterLayer, buildPeakLayer, type CellRef } from "./ivtRasterLayer";
import { buildDrapeSampler, drapeColors, type ReliefData } from "./reliefLayer";

/** Milliseconds between replay frames (one frame = one hour). */
export const REPLAY_INTERVAL_MS = 250;

export interface CellReading {
  lat: number;
  lon: number;
  value: number | null;
  timeMs: number;
  /** "max": the event's maximum at the cell (footprint view); "hour": the value of the current hourly frame. */
  kind: "hour" | "max";
}

/** What the count map shows: n events in the selection, the busiest cell, and the dates they cover. */
export interface CountInfo {
  n: number;
  max: number;
  from: string | null;
  to: string | null;
}

const NO_EVENTS: ArEvent[] = [];

export interface ArViewOptions {
  /** Relief drawn below the IVT (null/undefined: none). */
  relief?: ReliefData | null;
  /** "drape" (default): IVT colors the relief, or the cell raster when there is no relief; "isolines": contour lines. */
  view?: IvtView;
  /** Year/month toggles: with no event selected the count map covers the events they leave on (default: all). */
  toggles?: ArToggles;
}

/**
 * Events of an `events` layer with hourly IVT frames: selection, replay clock and picked cell. The IVT cells are always
 * built (pickable, for the readings); they only show a fill when no relief carries the IVT as a drape.
 * `drapeColors` (RGBA per relief point) is set in the drape view with relief and an event selected.
 */
export function useArEvents(
  layer: LayerManifest | undefined,
  active: boolean,
  { relief = null, view = "drape", toggles = DEFAULT_TOGGLES }: ArViewOptions = {},
) {
  const layerId = layer?.id;
  const eventsFile = layer?.files.find((f) => f.endsWith("events.json"));
  const indexFile = layer?.files.find((f) => f === "frames/index.json");

  const [data, setData] = useState<{ events: ArEvent[]; index: FramesIndex } | null>(null);
  const [failed, setFailed] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [frameSets, setFrameSets] = useState<Record<string, Float32Array>>({});
  const [footprints, setFootprints] = useState<Footprints | null>(null);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [hover, setHover] = useState<CellRef | null>(null);
  const [picked, setPicked] = useState<CellRef | null>(null);
  const [wasActive, setWasActive] = useState(active);
  const theme = useTheme();
  const requested = useRef(new Set<string>());

  // Turning the layer off clears the selection and stops the replay (state adjusted during render).
  if (wasActive !== active) {
    setWasActive(active);
    if (!active) {
      setSelectedEventId(null);
      setPlaying(false);
      setHover(null);
      setPicked(null);
    }
  }

  const events = data?.events ?? NO_EVENTS;
  const index = data?.index ?? null;
  const status: "idle" | "loading" | "ready" | "error" = failed
    ? "error"
    : data
      ? "ready"
      : active && eventsFile && indexFile
        ? "loading"
        : "idle";

  useEffect(() => {
    if (!active || !layerId || !eventsFile || !indexFile || data || failed) return;
    let cancelled = false;
    Promise.all([fetchLayerData<ArEvent[]>(layerId, eventsFile), fetchLayerData<FramesIndex>(layerId, indexFile)])
      .then(([e, i]) => !cancelled && setData({ events: e, index: i }))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [active, layerId, eventsFile, indexFile, data, failed]);

  const selectedEvent = events.find((e) => e.event_id === selectedEventId) ?? null;
  const entry = selectedEventId && index ? index.events[selectedEventId] : undefined;
  const nFrames = entry?.n_frames ?? 0;
  const frames = selectedEventId ? (frameSets[selectedEventId] ?? null) : null;

  useEffect(() => {
    if (!layerId || !index || !selectedEventId || !entry || requested.current.has(selectedEventId)) return;
    requested.current.add(selectedEventId);
    const id = selectedEventId;
    fetchFrames(layerId, id)
      .then((b) => setFrameSets((prev) => ({ ...prev, [id]: parseFrames(b, index.grid, entry.n_frames) })))
      .catch(() => requested.current.delete(id));
  }, [layerId, index, selectedEventId, entry]);

  // Footprints (max |IVT| per cell and event): for the count map and the start of a replay. Optional in the layer.
  const fpMeta = index?.footprints;
  const fpFile = fpMeta && layer?.files.includes(fpMeta.file) ? fpMeta.file : null;
  useEffect(() => {
    if (!active || !layerId || !fpMeta || !fpFile || footprints) return;
    let cancelled = false;
    fetchLayerBinary(layerId, fpFile)
      .then((b) => !cancelled && setFootprints(parseFootprints(b, fpMeta)))
      .catch(() => undefined); // without footprints the viewer falls back to the hourly frames only
    return () => {
      cancelled = true;
    };
  }, [active, layerId, fpMeta, fpFile, footprints]);

  // The replay stops on its last frame.
  const atEnd = nFrames > 0 && frame >= nFrames - 1;
  const isPlaying = playing && !atEnd;
  useEffect(() => {
    if (!isPlaying) return;
    const timer = setInterval(() => setFrame((k) => Math.min(k + 1, nFrames - 1)), REPLAY_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [isPlaying, nFrames]);

  const select = useCallback((id: string) => {
    setSelectedEventId(id);
    setFrame(0);
    setPlaying(false);
    setPicked(null);
    setHover(null);
  }, []);

  const toggle = useCallback(() => {
    // From the last frame, play restarts the replay.
    if (!isPlaying && atEnd) setFrame(0);
    setPlaying(!isPlaying);
  }, [isPlaying, atEnd]);

  const seek = useCallback(
    (k: number) => {
      setPlaying(false);
      setFrame(Math.max(0, Math.min(Math.max(nFrames - 1, 0), Math.round(k))));
    },
    [nFrames],
  );
  const step = useCallback((d: number) => seek(frame + d), [seek, frame]);

  const cells = useMemo(() => (index ? gridCells(index.grid) : []), [index]);
  const grid = index?.grid;
  const sampler = useMemo(() => (relief && grid ? buildDrapeSampler(relief, grid) : null), [relief, grid]);
  // The start of a replay (frame 0, not playing) shows the event's footprint; playing or scrubbing shows the hours.
  const footprint = useMemo(
    () => (footprints && selectedEventId ? footprintOf(footprints, selectedEventId) : null),
    [footprints, selectedEventId],
  );
  const footprintShown = !!footprint && frame === 0 && !isPlaying;
  const field = footprintShown ? footprint : frames;
  const fieldFrame = footprintShown ? 0 : frame;
  const drape = useMemo(
    () =>
      view === "drape" && field && relief && sampler ? drapeColors(relief, sampler, field, fieldFrame, theme) : null,
    [view, field, relief, sampler, fieldFrame, theme],
  );

  const filtered = useMemo(() => filterEvents(events, toggles), [events, toggles]);
  const counts = useMemo(
    () => (footprints ? countReaching(footprints, filtered.map((e) => e.event_id)) : null),
    [footprints, filtered],
  );
  const count = useMemo((): CountInfo | null => {
    if (!counts || selectedEventId) return null;
    const have = filtered.filter((e) => footprints!.order.includes(e.event_id));
    const starts = have.map((e) => e.start.slice(0, 10)).sort();
    const ends = have.map((e) => e.end.slice(0, 10)).sort();
    return {
      n: have.length,
      max: counts.reduce((m, v) => Math.max(m, v), 0),
      from: starts[0] ?? null,
      to: ends[ends.length - 1] ?? null,
    };
  }, [counts, selectedEventId, filtered, footprints]);

  const deckLayers = useMemo((): Layer[] => {
    if (!active || !layerId || !index) return []; // a layer that is off draws nothing, whatever is still loaded
    if (!selectedEventId) {
      return count && counts ? [buildCountLayer({ layerId, grid: index.grid, cells, counts, max: count.max, theme })] : [];
    }
    if (!field) return [];
    const eventKey = footprintShown ? `${selectedEventId}:max` : selectedEventId;
    const raster = buildIvtRasterLayer({
      layerId,
      eventId: eventKey,
      grid: index.grid,
      cells,
      frames: field,
      frame: fieldFrame,
      theme,
      picked,
      showFill: view === "drape" && !relief,
      onHover: setHover,
      onPick: setPicked,
    });
    const common = { layerId, grid: index.grid, frames: field, frame: fieldFrame, theme };
    const level = footprintShown ? coreLevel(field) : null;
    return [
      raster,
      ...(view === "isolines" ? buildIvtContourLayers({ ...common, eventId: eventKey }) : []),
      ...(level != null
        ? buildIvtContourLayers({ ...common, eventId: `${eventKey}:core`, levels: [level], idSuffix: "-core" })
        : []),
      ...(selectedEvent?.ivt_max_lat != null && selectedEvent.ivt_max_lon != null
        ? [buildPeakLayer({ layerId, lon: selectedEvent.ivt_max_lon, lat: selectedEvent.ivt_max_lat, theme })]
        : []),
    ];
  }, [active, layerId, index, selectedEventId, selectedEvent, field, fieldFrame, footprintShown, cells, theme, picked, view, relief, count, counts]);

  const startIso = entry?.start;
  const timeMs = startIso ? frameTime(startIso, frame, index?.step_hours) : null;
  const ref = hover ?? picked;
  const reading: CellReading | null =
    ref && index && field && timeMs != null
      ? {
          lat: cells[ref.row * index.grid.nx + ref.col]!.lat,
          lon: cells[ref.row * index.grid.nx + ref.col]!.lon,
          value: frameValue(field, index.grid, fieldFrame, ref.row, ref.col),
          timeMs,
          kind: footprintShown ? "max" : "hour",
        }
      : null;

  return {
    status,
    events,
    units: index?.units ?? "",
    selectedEvent,
    selectedEventId,
    loadingFrames: !!selectedEventId && !frames,
    frame,
    nFrames,
    playing: isPlaying,
    cursorMs: timeMs,
    reading,
    deckLayers,
    count,
    drapeColors: drape,
    select,
    toggle,
    seek,
    step,
  };
}

export type ArEventsState = ReturnType<typeof useArEvents>;
