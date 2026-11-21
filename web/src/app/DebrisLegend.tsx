import { es } from "../i18n/es";
import { fmtQ } from "../layers/debrisCatchments";

const STOPS = [0, 1, 2, 3, 4].map((i) => `var(--debris-${i})`).join(", ");

/** Peak-discharge legend of the debris layer (log scale between the smallest and the largest peak of the selection). */
export function DebrisLegend({ domain, source }: { domain: [number, number] | null; source: string }) {
  const mid = domain ? Math.sqrt(domain[0] * domain[1]) : null;
  const ticks = domain ? [domain[0], mid!, domain[1]] : [];
  return (
    <div className="map-legend map-legend-debris" data-testid="debris-legend" role="group" aria-label={es.debris.legendLabel}>
      <div className="map-legend-title">{es.debris.legendTitle}</div>
      <div className="map-legend-bar" style={{ background: `linear-gradient(to right, ${STOPS})` }} />
      <div className="map-legend-ticks" data-testid="debris-legend-ticks">
        {ticks.map((v, i) => (
          <span key={i} style={{ left: `${i * 50}%` }}>
            {fmtQ(v)}
          </span>
        ))}
      </div>
      <div className="map-legend-note">{es.debris.legendNote}</div>
      <div className="map-legend-source">{es.debris.legendSource(source)}</div>
    </div>
  );
}
