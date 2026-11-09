import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Layer } from "@deck.gl/core";
import { fetchFrames, fetchLayerData, type ArEvent, type FramesIndex, type LayerManifest } from "../api/client";
import { useTheme } from "../theme/themeStore";
import { frameTime, frameValue, gridCells, parseFrames } from "./arEvents";
import { buildIvtRasterLayer, type CellRef } from "./ivtRasterLayer";

/** Milliseconds between replay frames (one frame = one hour). */
export const REPLAY_INTERVAL_MS = 250;

export interface CellReading {
  lat: number;
  lon: number;
  value: number | null;
  timeMs: number;
}

/** Events of an `events` layer with hourly IVT frames: selection, replay clock and picked cell. */
export function useArEvents(layer: LayerManifest | undefined, active: boolean, opacity = 1) {
  const layerId = layer?.id;
  const eventsFile = layer?.files.find((f) => f.endsWith("events.json"));
  const indexFile = layer?.files.find((f) => f === "frames/index.json");

  const [data, setData] = useState<{ events: ArEvent[]; index: FramesIndex } | null>(null);
  const [failed, setFailed] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [frameSets, setFrameSets] = useState<Record<string, Float32Array>>({});
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

  const events = data?.events ?? [];
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
  const deckLayers = useMemo((): Layer[] => {
    if (!layerId || !index || !selectedEventId || !frames) return [];
    return [
      buildIvtRasterLayer({
        layerId,
        eventId: selectedEventId,
        grid: index.grid,
        cells,
        frames,
        frame,
        theme,
        picked,
        opacity,
        onHover: setHover,
        onPick: setPicked,
      }),
    ];
  }, [layerId, index, selectedEventId, frames, cells, frame, theme, picked, opacity]);

  const startIso = entry?.start;
  const timeMs = startIso ? frameTime(startIso, frame, index?.step_hours) : null;
  const ref = hover ?? picked;
  const reading: CellReading | null =
    ref && index && frames && timeMs != null
      ? {
          lat: cells[ref.row * index.grid.nx + ref.col]!.lat,
          lon: cells[ref.row * index.grid.nx + ref.col]!.lon,
          value: frameValue(frames, index.grid, frame, ref.row, ref.col),
          timeMs,
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
    select,
    toggle,
    seek,
    step,
  };
}

export type ArEventsState = ReturnType<typeof useArEvents>;
