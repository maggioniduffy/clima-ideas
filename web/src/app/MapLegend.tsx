import { es } from "../i18n/es";
import {
  IVT_ALPHA_HIGH,
  IVT_ALPHA_LOW,
  IVT_SCALE_MAX,
  ivtColor,
  legendTicks,
  rgbCss,
  type IvtView,
} from "../layers/arEvents";
import { IVT_CONTOUR_LEVELS, IVT_CONTOUR_WIDTHS } from "../layers/ivtContours";
import { useTheme } from "../theme/themeStore";

const STOPS = [0, 1, 2, 3, 4, 5].map((i) => `var(--ivt-${i})`).join(", ");
const TICKS = legendTicks();
const pct = (v: number) => `${((v / IVT_SCALE_MAX) * 100).toFixed(2).replace(/\.?0+$/, "")}%`;
/** Fade overlay (legend background over the ramp): opaque up to IVT_ALPHA_LOW, transparent from IVT_ALPHA_HIGH, like the raster. */
const FADE = `linear-gradient(to right, var(--surface) ${pct(IVT_ALPHA_LOW)}, rgba(0, 0, 0, 0) ${pct(IVT_ALPHA_HIGH)})`;

const VIEWS: { view: IvtView; label: string }[] = [
  { view: "drape", label: es.map.viewDrape },
  { view: "isolines", label: es.map.viewIsolines },
];

/** IVT legend: view toggle, then the color scale (drape) or the contour levels (isolines), and the outline source. */
export function MapLegend({ view, onViewChange }: { view: IvtView; onViewChange: (v: IvtView) => void }) {
  const theme = useTheme();
  return (
    <div className="map-legend" data-testid="map-legend" role="group" aria-label={es.map.legendLabel}>
      <div className="map-legend-title">{es.map.legendTitle}</div>
      <div className="map-legend-views" role="group" aria-label={es.map.viewLabel}>
        {VIEWS.map((v) => (
          <button
            key={v.view}
            type="button"
            data-testid={`ivt-view-${v.view}`}
            aria-pressed={view === v.view}
            onClick={() => onViewChange(v.view)}
          >
            {v.label}
          </button>
        ))}
      </div>
      {view === "drape" ? (
        <>
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
        </>
      ) : (
        <ul className="map-legend-levels" data-testid="map-legend-levels">
          {IVT_CONTOUR_LEVELS.map((level, i) => (
            <li key={level} data-level={level}>
              <span
                className="map-legend-line"
                data-testid="level-line"
                style={{ height: `${IVT_CONTOUR_WIDTHS[i]}px`, background: rgbCss(ivtColor(level, theme)) }}
              />
              {level}
            </li>
          ))}
        </ul>
      )}
      <div className="map-legend-source">{es.map.outlineSource}</div>
    </div>
  );
}
