import { es } from "../i18n/es";
import { legendTicks } from "../layers/arEvents";

const STOPS = [0, 1, 2, 3, 4, 5].map((i) => `var(--ivt-${i})`).join(", ");
const TICKS = legendTicks();

/** IVT color scale (same ramp tokens as the raster) with its tick values and the outline source. */
export function MapLegend() {
  return (
    <div className="map-legend" data-testid="map-legend" role="group" aria-label={es.map.legendLabel}>
      <div className="map-legend-title">{es.map.legendTitle}</div>
      <div className="map-legend-bar" style={{ background: `linear-gradient(to right, ${STOPS})` }} />
      <div className="map-legend-ticks" data-testid="map-legend-ticks">
        {TICKS.map((t) => (
          <span key={t.value} data-value={t.value} style={{ left: `${t.fraction * 100}%` }}>
            {t.label}
          </span>
        ))}
      </div>
      <div className="map-legend-source">{es.map.outlineSource}</div>
    </div>
  );
}
