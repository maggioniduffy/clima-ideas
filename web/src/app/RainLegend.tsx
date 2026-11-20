import { es } from "../i18n/es";
import { formatUtc } from "../layers/arEvents";
import { rainLegendTicks } from "../layers/convectionIdf";

const STOPS = [0, 1, 2, 3, 4].map((i) => `var(--rain-${i})`).join(", ");
const TICKS = rainLegendTicks();

/** Rain legend of the convection layer; it goes in the map's legend stack (`.map-legends`). */
export function RainLegend({ source }: { source: string }) {
  return (
    <div className="map-legend map-legend-rain" data-testid="rain-legend" role="group" aria-label={es.convection.legendLabel}>
      <div className="map-legend-title">{es.convection.legendTitle}</div>
      <div className="map-legend-bar" style={{ background: `linear-gradient(to right, ${STOPS})` }} />
      <div className="map-legend-ticks" data-testid="rain-legend-ticks">
        {TICKS.map((t) => (
          <span key={t.value} data-value={t.value} style={{ left: `${t.fraction * 100}%` }}>
            {t.label}
          </span>
        ))}
      </div>
      <div className="map-legend-note">{es.convection.legendLow}</div>
      <div className="map-legend-source">{es.convection.legendSource(source)}</div>
      <div className="map-legend-source">{es.map.outlineSource}</div>
    </div>
  );
}

/** Replay clock of the convection layer; it goes in the map's clock stack (`.map-clocks`). */
export function RainClock({ cursorMs }: { cursorMs: number | null }) {
  if (cursorMs == null) return null;
  return (
    <div className="map-clock" data-testid="rain-clock" aria-label={es.convection.clockLabel}>
      <div className="num map-clock-time">{formatUtc(cursorMs)}</div>
    </div>
  );
}
