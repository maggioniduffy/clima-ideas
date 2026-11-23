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
import { basemapAvailable, buildBasemapLayer } from "../layers/basemapLayer";
import { buildReliefLayer } from "../layers/reliefLayer";
import { useReferenceLayers } from "../layers/referenceLayers";
import { CONVECTION_LAYER_ID } from "../layers/convectionIdf";
import { useConvectionIdf } from "../layers/useConvectionIdf";
import { DEBRIS_LAYER_ID } from "../layers/debrisCatchments";
import { useDebrisCatchments } from "../layers/useDebrisCatchments";
import { ANALOGS_LAYER_ID, HINDCAST_LAYER_ID } from "../layers/hindcast";
import { FORECAST_LAYER_ID } from "../layers/forecast";
import { useForecastOutlook } from "../layers/useForecastOutlook";
import { useHindcast } from "../layers/useHindcast";
import { isReliefLayer, useLayers } from "../layers/useLayers";
import { useTheme } from "../theme/themeStore";
import { ClockBox } from "./ClockBox";
import { DebrisLegend } from "./DebrisLegend";
import { DetailCard } from "./DetailCard";
import { EventListCard } from "./EventListCard";
import { Inspector } from "./Inspector";
import { LayerPanel } from "./LayerPanel";
import { MapBackground, RELIEF_OPACITY_BOTH, effectiveBackground, readBackground, reliefVisible, writeBackground, type MapBackgroundMode } from "./MapBackground";
import { MapCanvas } from "./MapCanvas";
import { MapLegend } from "./MapLegend";
import { RainClock, RainLegend } from "./RainLegend";
import { PanelResizer } from "./PanelResizer";
import {
  clampAll,
  clampSize,
  limitsFor,
  loadSizes,
  PANEL_LIMITS,
  saveSizes,
  timelineMinFor,
  type PanelId,
  type PanelSizes,
} from "./panelSizes";
import { Hero } from "./Hero";
import { heroStats, type HeroInput } from "./heroStats";
import { Timeline } from "./Timeline";
import { TopBar } from "./TopBar";
import "./shell.css";

const viewport = () => ({ width: window.innerWidth, height: window.innerHeight });
/** Same breakpoint as the narrow-screen rules in shell.css: everything stacks and there are no handles. */
const NARROW_MAX_W = 800;
/** Above this height the timeline is a tall card instead of a pill (a 999 px radius would swallow its content). */
const TALL_TIMELINE = 200;

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
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setExpanded(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);
  // the map keeps its size under the expanded panel; nudge listeners (deck.gl) after it is uncovered again
  useEffect(() => {
    if (!expanded) window.dispatchEvent(new Event("resize"));
  }, [expanded]);
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
  const [storedBackground, setBackgroundState] = useState<MapBackgroundMode>(readBackground);
  // Without a CARTO key there is no basemap: the control only switches the relief on and off.
  const hasBasemap = basemapAvailable();
  const background: MapBackgroundMode = effectiveBackground(storedBackground, hasBasemap);
  const setBackground = (m: MapBackgroundMode) => {
    setBackgroundState(m);
    writeBackground(m);
  };
  const basemap = useMemo(
    () => (hasBasemap ? buildBasemapLayer(theme, background !== "relief") : null),
    [hasBasemap, theme, background],
  );
  // AR event filter: year and month toggles, ranking key and the "top N" switch (state lives here, no store).
  // A selected event that the filter hides stays selected: the map and the replay keep working.
  const [arToggles, setArToggles] = useState<ArToggles>(DEFAULT_TOGGLES);
  const [arSortKey, setArSortKey] = useState<SortKey>("ivt_max");
  const [arTopOn, setArTopOn] = useState(false);
  const ar = useArEvents(eventsLayer, eventsActive, { relief: s.activeRelief?.data ?? null, view: ivtView, toggles: arToggles });
  // In the drape view the relief itself carries the IVT: swap its slate colors for the frame's drape colors.
  const reliefOpacity = background === "both" ? RELIEF_OPACITY_BOTH : 1;
  const baseLayers = useMemo(
    () =>
      s.deckLayers.map((l) => {
        if (!l.id.startsWith("relief-")) return l;
        if (!reliefVisible(background)) return l.clone({ visible: false });
        return ar.drapeColors && s.activeRelief && l.id === `relief-${s.activeRelief.layerId}`
          ? buildReliefLayer(s.activeRelief.layerId, s.activeRelief.data, theme, ar.drapeColors, reliefOpacity)
          : reliefOpacity === 1
            ? l
            : l.clone({ opacity: reliefOpacity });
      }),
    [s.deckLayers, s.activeRelief, ar.drapeColors, theme, background, reliefOpacity],
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
  const convLayer = s.layers.find((l) => l.id === CONVECTION_LAYER_ID);
  const convActive = !!convLayer && s.activeIds.has(convLayer.id);
  const conv = useConvectionIdf(convLayer, convActive);
  const debrisLayer = s.layers.find((l) => l.id === DEBRIS_LAYER_ID);
  const debrisActive = !!debrisLayer && s.activeIds.has(debrisLayer.id);
  const debris = useDebrisCatchments(debrisLayer, debrisActive);
  const hindcastLayer = s.layers.find((l) => l.id === HINDCAST_LAYER_ID);
  const hindcastActive = !!hindcastLayer && s.activeIds.has(hindcastLayer.id);
  const hindcast = useHindcast(hindcastLayer, s.layers.find((l) => l.id === ANALOGS_LAYER_ID), hindcastActive);
  const forecastLayer = s.layers.find((l) => l.id === FORECAST_LAYER_ID);
  const forecastActive = !!forecastLayer && s.activeIds.has(forecastLayer.id);
  const forecast = useForecastOutlook(forecastLayer, forecastActive);
  const refLayers = useReferenceLayers();
  const arVisible = useMemo(
    () => visibleEvents(ar.events, arToggles, arSortKey, arTopOn, TOP_N, ratios),
    [ar.events, arToggles, arSortKey, arTopOn, ratios],
  );
  // Hero numbers: only what the selected layer's own panel already computes.
  const sel = s.selectedLayer;
  const heroInput: HeroInput = {};
  if (sel && s.activeIds.has(sel.id)) {
    if (sel.id === eventsLayer?.id && ar.status === "ready") heroInput.events = { shown: arVisible.events.length, total: ar.events.length };
    if (s.selectedFeatures.length > 0) heroInput.points = { count: s.selectedFeatures.length, station: sel.id === FLOOD_LAYER_ID };
    if (sel.id === debrisLayer?.id && debris.status === "ready") heroInput.catchments = debris.shownCount;
  }
  const hero = heroStats(heroInput);
  const activeName = sel && s.activeIds.has(sel.id) && !isReliefLayer(sel) ? (es.layers.short[sel.id] ?? sel.title) : null;
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
  // Replay rows stack (storm replay, AR replay): the strip grows to hold them unless it is collapsed (0) or the window is narrow.
  const timelineRows = { convection: convActive && conv.status === "ready", ar: !!ar.selectedEvent };
  const timelineH = sizes.timeline === 0 ? 0 : Math.max(sizes.timeline, timelineMinFor(timelineRows));
  return (
    <div
      className="shell"
      data-testid="shell"
      style={
        {
          "--panels-w": `${sizes.panels}px`,
          "--timeline-h": `${timelineH}px`,
          // free edges of the map area: the floating panels sit 16 px from the window and 16 px apart
          "--right-inset": collapsed("panels") ? "16px" : `${sizes.panels + 32}px`,
          "--bottom-inset": collapsed("timeline") ? "16px" : `${timelineH + 32}px`,
          "--panels-handle-r": collapsed("panels") ? "0px" : `${sizes.panels + 16}px`,
          "--timeline-handle-b": collapsed("timeline") ? "0px" : `${timelineH + 10}px`,
        } as CSSProperties
      }
    >
      <TopBar activeName={activeName}>
        <LayerPanel
          layers={s.layers}
          status={s.status}
          activeIds={s.activeIds}
          selectedId={s.selectedId}
          onToggle={s.toggle}
          onSelect={s.select}
        />
      </TopBar>
      <div className="shell-body" data-expanded={expanded ? "" : undefined}>
        <MapCanvas
          basemap={basemap}
          markers={conv.markers}
          focus={debris.focus}
          layers={[
            ...mapLayers.filter((l) => !isFlood(l)),
            ...ar.deckLayers,
            ...conv.deckLayers,
            ...debris.deckLayers,
            ...mapLayers.filter(isFlood),
            ...refLayers,
          ]}
        >
          <div className="map-legends" data-testid="map-legends">
            {eventsActive && <MapLegend view={ivtView} onViewChange={setIvtView} count={ar.count} />}
            {convActive && convLayer && conv.status === "ready" && <RainLegend source={convLayer.source} />}
            {debrisActive && debrisLayer && debris.status === "ready" && (
              <DebrisLegend domain={debris.domain} source={debrisLayer.source} />
            )}
          </div>
          <MapBackground value={background} onChange={setBackground} hasBasemap={hasBasemap} />
          <div className="map-clocks" data-testid="map-clocks">
            {ar.selectedEvent && ar.cursorMs != null && (
              <ClockBox cursorMs={ar.cursorMs} frame={ar.frame} nFrames={ar.nFrames} />
            )}
            {convActive && convLayer && conv.status === "ready" && <RainClock cursorMs={conv.cursorMs} />}
          </div>
        </MapCanvas>
        <PanelResizer className="panel-resizer panel-resizer-panels" orientation="vertical" dir={-1} {...resizer("panels")} />
        {/* Right column: layer list, inspector, detail card and event list stacked; it scrolls only as a fallback. */}
        <div className="shell-panels glass" data-testid="panels-slot" hidden={collapsed("panels")}>
        <div className="panels-head">
          <Hero title={s.selectedLayer?.title ?? es.appTitle} stats={hero} source={hero.length > 0 && s.selectedLayer ? s.selectedLayer : null} />
          <button
            type="button"
            className="panel-expand"
            data-testid="panel-expand"
            aria-label={expanded ? es.panel.collapse : es.panel.expand}
            aria-expanded={expanded}
            onClick={() => setExpanded((e) => !e)}
          >
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              {expanded ? (
                <path d="M7 2v5H2M11 16v-5h5M7 7 2 2M11 11l5 5" />
              ) : (
                <path d="M2 7V2h5M16 11v5h-5M2 2l5 5M16 16l-5-5" />
              )}
            </svg>
          </button>
        </div>

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
            convection={
              convActive && convLayer && s.selectedLayer?.id === convLayer.id
                ? { state: conv, source: convLayer.source, period: convLayer.period }
                : null
            }
            debris={
              debrisActive && debrisLayer && s.selectedLayer?.id === debrisLayer.id
                ? { state: debris, source: debrisLayer.source, period: debrisLayer.period }
                : null
            }
            hindcast={
              hindcastActive && hindcastLayer && s.selectedLayer?.id === hindcastLayer.id
                ? { state: hindcast, source: hindcastLayer.source, period: hindcastLayer.period, license: hindcastLayer.license }
                : null
            }
            forecast={
              forecastActive && forecastLayer && s.selectedLayer?.id === forecastLayer.id
                ? { state: forecast, source: forecastLayer.source, period: forecastLayer.period, license: forecastLayer.license, outlookStatus: forecastLayer.outlook_status }
                : null
            }
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
              ensoStatus={enso.status}
              ensoOpen={showEnso}
              onToggleEnso={() => setEnsoOpen((o) => !o)}
            />
          )}
        </div>
        <PanelResizer className="panel-resizer panel-resizer-timeline" orientation="horizontal" dir={-1} {...resizer("timeline")} />
        <div className="timeline-slot glass" data-testid="timeline-slot" data-tall={timelineH > TALL_TIMELINE ? "" : undefined} hidden={collapsed("timeline")}>
          <Timeline
            events={eventsActive ? arVisible.filtered : []}
            peakIds={arVisible.peakIds}
            period={eventsLayer?.period}
            selectedEventId={ar.selectedEventId}
            onSelectEvent={selectEvent}
            replay={ar.selectedEvent ? ar : null}
            convection={convActive ? conv : null}
          />
        </div>
      </div>
    </div>
  );
}
