import { useCallback, useEffect, useMemo, useState } from "react";
import type { Layer } from "@deck.gl/core";
import { fetchFrames, fetchLayerData, type FramesIndex, type LayerManifest } from "../api/client";
import { useTheme } from "../theme/themeStore";
import { frameTime, gridCells, parseFrames } from "./arEvents";
import type { IdfData, ReplayData } from "./convectionIdf";
import { buildCellLayers, convectionMarkers, gridStepDeg } from "./convectionStation";
import { buildRainRasterLayer } from "./rainRasterLayer";

/** Milliseconds between replay frames (one frame = 30 min of IMERG; 144 frames last ~17 s). */
export const CONVECTION_REPLAY_MS = 120;

interface Loaded {
  idf: IdfData;
  replay: ReplayData;
  index: FramesIndex;
  frames: Float32Array;
}

const fileOf = (layer: LayerManifest | undefined, name: string) => layer?.files.find((f) => f === name);

/**
 * `convection-idf` layer (F3.5): the IDF curves, the storm replay (half-hourly IMERG frames) and its clock.
 * Loads everything when the layer is switched on; turning it off stops the replay.
 */
export function useConvectionIdf(layer: LayerManifest | undefined, active: boolean) {
  const layerId = layer?.id;
  const idfFile = fileOf(layer, "idf.json");
  const replayFile = fileOf(layer, "replay.json");
  const indexFile = fileOf(layer, "frames/index.json");
  const [data, setData] = useState<Loaded | null>(null);
  const [failed, setFailed] = useState(false);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [wasActive, setWasActive] = useState(active);
  const theme = useTheme();

  if (wasActive !== active) {
    setWasActive(active);
    if (active) setFailed(false); // switching the layer back on retries a failed load
    if (!active) {
      setPlaying(false);
      setFrame(0);
    }
  }

  useEffect(() => {
    if (!active || !layerId || !idfFile || !replayFile || !indexFile || data || failed) return;
    let cancelled = false;
    (async () => {
      const [idf, replay, index] = await Promise.all([
        fetchLayerData<IdfData>(layerId, idfFile),
        fetchLayerData<ReplayData>(layerId, replayFile),
        fetchLayerData<FramesIndex>(layerId, indexFile),
      ]);
      const entry = index.events[replay.event.id];
      if (!entry) throw new Error("frames index without the replay set");
      const frames = parseFrames(await fetchFrames(layerId, replay.event.id), index.grid, entry.n_frames);
      if (!cancelled) setData({ idf, replay, index, frames });
    })().catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [active, layerId, idfFile, replayFile, indexFile, data, failed]);

  const status: "idle" | "loading" | "ready" | "error" = failed
    ? "error"
    : data
      ? "ready"
      : active && idfFile && replayFile && indexFile
        ? "loading"
        : "idle";
  const nFrames = data?.replay.event.n_frames ?? 0;
  const atEnd = nFrames > 0 && frame >= nFrames - 1;
  const isPlaying = playing && !atEnd;

  useEffect(() => {
    if (!isPlaying) return;
    const timer = setInterval(() => setFrame((k) => Math.min(k + 1, nFrames - 1)), CONVECTION_REPLAY_MS);
    return () => clearInterval(timer);
  }, [isPlaying, nFrames]);

  const seek = useCallback(
    (k: number) => {
      setPlaying(false); // scrubbing or stepping pauses the replay
      setFrame(Math.min(Math.max(0, k), Math.max(nFrames - 1, 0)));
    },
    [nFrames],
  );
  const step = useCallback((d: number) => seek(frame + d), [seek, frame]);
  const toggle = useCallback(() => {
    if (isPlaying) {
      setPlaying(false);
      return;
    }
    if (atEnd) setFrame(0); // play again from the start
    setPlaying(true);
  }, [isPlaying, atEnd]);

  const cursorMs = data
    ? frameTime(data.replay.event.start, frame, data.replay.event.step_minutes / 60)
    : null;

  const cells = useMemo(() => (data ? gridCells(data.index.grid) : []), [data]);
  const deckLayers = useMemo<Layer[]>(
    () =>
      active && layerId && data
        ? [
            buildRainRasterLayer({ layerId, grid: data.index.grid, cells, frames: data.frames, frame, theme }),
            ...buildCellLayers(data.replay, gridStepDeg(data.index.grid), theme),
          ]
        : [],
    [active, layerId, data, cells, frame, theme],
  );
  const markers = useMemo(
    () => (active && data ? convectionMarkers(data.replay, gridStepDeg(data.index.grid)) : []),
    [active, data],
  );

  return {
    status,
    idf: data?.idf ?? null,
    replay: data?.replay ?? null,
    nFrames,
    frame,
    playing: isPlaying,
    cursorMs,
    toggle,
    step,
    seek,
    deckLayers,
    markers,
  };
}

export type ConvectionState = ReturnType<typeof useConvectionIdf>;
