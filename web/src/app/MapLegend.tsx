import { es } from "../i18n/es";
import { IVT_ALPHA_HIGH, IVT_ALPHA_LOW, IVT_SCALE_MAX, legendTicks } from "../layers/arEvents";

const STOPS = [0, 1, 2, 3, 4, 5].map((i) => `var(--ivt-${i})`).join(", ");
const TICKS = legendTicks();
const pct = (v: number) => `${((v / IVT_SCALE_MAX) * 100).toFixed(2).replace(/\.?0+$/, "")}%`;
/** Fade overlay (legend background over the ramp): opaque up to IVT_ALPHA_LOW, transparent from IVT_ALPHA_HIGH, like the raster. */
const FADE = `linear-gradient(to right, var(--surface) ${pct(IVT_ALPHA_LOW)}, rgba(0, 0, 0, 0) ${pct(IVT_ALPHA_HIGH)})`;

/** IVT color scale (same ramp tokens as the raster) with its tick values and the outline source. */
export function MapLegend() {
  return (
    <div className="map-legend" data-testid="map-legend" role="group" aria-label={es.map.legendLabel}>
      <div className="map-legend-title">{es.map.legendTitle}</div>
      <div
        className="map-legend-bar"
        data-testid="map-legend-bar"
        style={{ background: `${FADE}, linear-gradient(to right, ${STOPS})` }}
      />
      <div className="map-legend-ticks" data-testid="map-legend-ticks">
        {TICKS.map((t) => (
          <span key={t.value} data-value={t.value} style={{ left: `${t.fraction * 100}%` }}>
            {t.label}
          </span>
        ))}
      </div>
      <div className="map-legend-note">{es.map.legendLow}</div>
      <div className="map-legend-source">{es.map.outlineSource}</div>
    </div>
  );
}
