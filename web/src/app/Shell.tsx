import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { es } from "../i18n/es";
import type { IvtView } from "../layers/arEvents";
import type { FloodStationFeature } from "../api/client";
import { buildFloodStationsLayer } from "../layers/floodStations";
import { FLOOD_LAYER_ID, useFloodStation } from "../layers/useFloodStation";
import { useArEvents } from "../layers/useArEvents";
import { useArResponses } from "../layers/useArResponses";
import { DEFAULT_TOGGLES, TOP_N, responseRatios, revealEvent, type ArToggles, type SortKey, visibleEvents } from "../layers/arFilter";
import { useEnsoExtremes } from "../layers/useEnsoExtremes";
import { useEnsoStats } from "../layers/useEnsoStats";
import { buildReliefLayer } from "../layers/reliefLayer";
import { useReferenceLayers } from "../layers/referenceLayers";
import { useLayers } from "../layers/useLayers";
import { useTheme } from "../theme/themeStore";
import { ClockBox } from "./ClockBox";
import { DetailCard } from "./DetailCard";
import { EventListCard } from "./EventListCard";
import { Inspector } from "./Inspector";
import { LayerPanel } from "./LayerPanel";
import { MapCanvas } from "./MapCanvas";
import { MapLegend } from "./MapLegend";
import { PanelResizer } from "./PanelResizer";
import {
  clampAll,
  clampSize,
  limitsFor,
  loadSizes,
  PANEL_LIMITS,
  saveSizes,
  type PanelId,
  type PanelSizes,
} from "./panelSizes";
import { Timeline } from "./Timeline";
import { TopBar, type Drawer } from "./TopBar";
import "./shell.css";

const viewport = () => ({ width: window.innerWidth, height: window.innerHeight });
/** Same breakpoint as the narrow-screen rules in shell.css: layers is a drawer and there are no handles. */
const NARROW_MAX_W = 800;

export function Shell() {
  // panel sizes (desktop only): the stored preference, re-clamped against the window on every render
  const [pref, setPref] = useState<PanelSizes>(loadSizes);
  const [vp, setVp] = useState(viewport);
  useEffect(() => {
    const onResize = () => setVp(viewport());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  const sizes = useMemo(() => clampAll(pref, vp), [pref, vp]);
  // A size of 0 is a collapsed (hidden) panel; narrow screens ignore it because they have no handles to bring it back.
  const narrow = vp.width <= NARROW_MAX_W;
  const collapsed = (panel: PanelId) => !narrow && sizes[panel] === 0;
  const resize = (panel: PanelId) => (value: number) =>
    setPref((cur) => {
      const next = { ...cur, [panel]: clampSize(panel, value, clampAll(cur, vp), vp) };
      saveSizes(next);
      return next;
    });
  const resizer = (panel: PanelId) => {
    const { min, max } = limitsFor(panel, sizes, vp);
    return {
      value: sizes[panel],
      min,
      max,
      defaultValue: PANEL_LIMITS[panel].def,
      label: es.resize[panel],
      testId: `resizer-${panel}`,
      onChange: resize(panel),
    };
  };

  // narrow screens: the side panels are drawers, one open at a time (CSS decides whether it applies)
  const [drawer, setDrawer] = useState<Drawer | null>(null);
  const toggleDrawer = (d: Drawer) => setDrawer((cur) => (cur === d ? null : d));
  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);
  const s = useLayers();
  const eventsLayer = s.layers.find((l) => l.kind === "events");
  const eventsActive = !!eventsLayer && s.activeIds.has(eventsLayer.id);
  const enso = useEnsoStats(eventsLayer, eventsActive);
  const ensoExtremes = useEnsoExtremes(eventsLayer, eventsActive);
  const responses = useArResponses(eventsLayer, eventsActive).data;
  const ratios = useMemo(() => responseRatios(responses), [responses]);
  const [ensoOpen, setEnsoOpen] = useState(false);
  const showEnso = ensoOpen && eventsActive && enso.status !== "none";
  const [ivtView, setIvtView] = useState<IvtView>("drape");
  const theme = useTheme();
  // AR event filter: year and month toggles, ranking key and the "top N" switch (state lives here, no store).
  // A selected event that the filter hides stays selected: the map and the replay keep working.
  const [arToggles, setArToggles] = useState<ArToggles>(DEFAULT_TOGGLES);
  const [arSortKey, setArSortKey] = useState<SortKey>("ivt_max");
  const [arTopOn, setArTopOn] = useState(false);
  const ar = useArEvents(eventsLayer, eventsActive, { relief: s.activeRelief?.data ?? null, view: ivtView, toggles: arToggles });
  // In the drape view the relief itself carries the IVT: swap its slate colors for the frame's drape colors.
  const baseLayers = useMemo(
    () =>
      ar.drapeColors && s.activeRelief
        ? s.deckLayers.map((l) =>
            l.id === `relief-${s.activeRelief!.layerId}`
              ? buildReliefLayer(s.activeRelief!.layerId, s.activeRelief!.data, theme, ar.drapeColors!)
              : l,
          )
        : s.deckLayers,
    [s.deckLayers, s.activeRelief, ar.drapeColors, theme],
  );
  // Flood stations replace the generic points layer: sized by value, hollow when regulated.
  const { select: selectLayer, selectPoint, selectedId, selectedPointId } = s;
  const mapLayers = useMemo(
    () =>
      baseLayers.map((l) =>
        l.id === `points-${FLOOD_LAYER_ID}`
          ? buildFloodStationsLayer(
              (l.props as { data: FloodStationFeature[] }).data,
              selectedId === FLOOD_LAYER_ID ? selectedPointId : null,
              theme,
              (f) => {
                selectLayer(FLOOD_LAYER_ID);
                selectPoint(f.id);
              },
            )
          : l,
      ),
    [baseLayers, selectedId, selectedPointId, theme, selectLayer, selectPoint],
  );
  // Stations go after the relief and IVT so nothing paints over them.
  const isFlood = (l: { id: string }) => l.id === `points-${FLOOD_LAYER_ID}`;
  // The flood station picked in the inspector list; its charts open in the detail card.
  const floodPoint =
    s.selectedLayer?.id === FLOOD_LAYER_ID ? (s.selectedFeatures.find((f) => f.id === s.selectedPointId) ?? null) : null;
  const flood = useFloodStation(floodPoint ? FLOOD_LAYER_ID : null, floodPoint?.id ?? null);
  const refLayers = useReferenceLayers();
  const arVisible = useMemo(
    () => visibleEvents(ar.events, arToggles, arSortKey, arTopOn, TOP_N, ratios),
    [ar.events, arToggles, arSortKey, arTopOn, ratios],
  );
  const selectEvent = (id: string) => {
    if (eventsLayer) s.select(eventsLayer.id);
    ar.select(id);
  };
  // Flood tag -> AR event: turn the ar-events layer on if needed, show it in the inspector and select the event once the
  // events are loaded; its year and month are switched back on so the filter never hides the selected event.
  const [pendingArId, setPendingArId] = useState<string | null>(null);
  const openArEvent = (id: string) => {
    if (!eventsLayer) return;
    if (eventsActive) s.select(eventsLayer.id);
    else s.toggle(eventsLayer.id);
    setPendingArId(id);
  };
  const pendingEvent = pendingArId ? ar.events.find((e) => e.event_id === pendingArId) : undefined;
  if (pendingArId && eventsActive && !pendingEvent && (ar.status === "error" || ar.status === "ready")) setPendingArId(null);
  if (pendingEvent && eventsActive) {
    setPendingArId(null);
    setArToggles((t) => revealEvent(t, pendingEvent));
    ar.select(pendingEvent.event_id);
  }
  return (
    <div
      className="shell"
      data-testid="shell"
      data-drawer={drawer ?? undefined}
      style={
        {
          "--layers-w": `${sizes.layers}px`,
          "--cards-h": `${sizes.cards}px`,
          "--timeline-h": `${sizes.timeline}px`,
        } as CSSProperties
      }
    >
      <TopBar drawer={drawer} onToggleDrawer={toggleDrawer} />
      <div className="shell-body">
        <div className="layers-slot card tx" data-testid="layers-slot" hidden={collapsed("layers")}>
          <LayerPanel
            layers={s.layers}
            status={s.status}
            activeIds={s.activeIds}
            selectedId={s.selectedId}
            onToggle={s.toggle}
            onSelect={s.select}
            events={
              eventsLayer && {
                layerId: eventsLayer.id,
                ensoStatus: enso.status,
                ensoOpen: showEnso,
                onToggleEnso: () => setEnsoOpen((o) => !o),
              }
            }
          />
        </div>
        <PanelResizer className="panel-resizer panel-resizer-layers" orientation="vertical" dir={1} {...resizer("layers")} />
        <div className="shell-main">
          <MapCanvas
            layers={[
              ...mapLayers.filter((l) => !isFlood(l)),
              ...ar.deckLayers,
              ...mapLayers.filter(isFlood),
              ...refLayers,
            ]}
          >
            {eventsActive && <MapLegend view={ivtView} onViewChange={setIvtView} count={ar.count} />}
            {ar.selectedEvent && ar.cursorMs != null && (
              <ClockBox cursorMs={ar.cursorMs} frame={ar.frame} nFrames={ar.nFrames} />
            )}
          </MapCanvas>
          <PanelResizer className="panel-resizer panel-resizer-cards" orientation="horizontal" dir={-1} {...resizer("cards")} />
          {/* Card row: inspector, then the detail card (ENSO table or station charts) and the event list. */}
          <div className="cards-row" data-testid="cards-row" hidden={collapsed("cards")}>
            <Inspector
              layer={s.selectedLayer}
              features={s.selectedFeatures}
              selectedPointId={s.selectedPointId}
              onSelectPoint={s.selectPoint}
              event={{ selected: ar.selectedEvent, loadingFrames: ar.loadingFrames, reading: ar.reading, responses }}
            />
            <DetailCard
              onOpenArEvent={openArEvent}
              flood={floodPoint ? flood : null}
              enso={
                showEnso && eventsLayer && enso.status !== "none"
                  ? {
                      status: enso.status,
                      stats: enso.data,
                      extremes: ensoExtremes.data,
                      source: eventsLayer.source,
                      period: eventsLayer.period,
                      onClose: () => setEnsoOpen(false),
                    }
                  : null
              }
            />
            {eventsActive && (
              <EventListCard
                status={ar.status}
                items={ar.events}
                shown={arVisible.events}
                toggles={arToggles}
                onTogglesChange={setArToggles}
                sortKey={arSortKey}
                onSortKeyChange={setArSortKey}
                topOn={arTopOn}
                onTopOnChange={setArTopOn}
                topN={TOP_N}
                hasResponses={!!responses}
                selectedEventId={ar.selectedEventId}
                onSelectEvent={selectEvent}
              />
            )}
          </div>
          <PanelResizer className="panel-resizer panel-resizer-timeline" orientation="horizontal" dir={-1} {...resizer("timeline")} />
          <div className="timeline-slot card tx" data-testid="timeline-slot" hidden={collapsed("timeline")}>
            <Timeline
              events={eventsActive ? arVisible.filtered : []}
              peakIds={arVisible.peakIds}
              period={eventsLayer?.period}
              selectedEventId={ar.selectedEventId}
              onSelectEvent={selectEvent}
              replay={ar.selectedEvent ? ar : null}
            />
          </div>
        </div>
      </div>
      <button
        type="button"
        className="drawer-scrim"
        data-testid="drawer-scrim"
        aria-label={es.drawers.close}
        tabIndex={-1}
        onClick={() => setDrawer(null)}
      />
    </div>
  );
}
