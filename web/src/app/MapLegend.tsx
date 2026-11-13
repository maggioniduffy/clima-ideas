import { es } from "../i18n/es";
import {
  IVT_ALPHA_HIGH,
  IVT_ALPHA_LOW,
  IVT_SCALE_MAX,
  countTicks,
  ivtColor,
  legendTicks,
  rgbCss,
  type IvtView,
} from "../layers/arEvents";
import type { CountInfo } from "../layers/useArEvents";
import { IVT_CONTOUR_LEVELS, IVT_CONTOUR_WIDTHS } from "../layers/ivtContours";
import { useTheme } from "../theme/themeStore";

const STOPS = [0, 1, 2, 3, 4, 5].map((i) => `var(--ivt-${i})`).join(", ");
const TICKS = legendTicks();
const pct = (v: number) => `${((v / IVT_SCALE_MAX) * 100).toFixed(2).replace(/\.?0+$/, "")}%`;
/** Fade overlay (legend background over the ramp): opaque up to IVT_ALPHA_LOW, transparent from IVT_ALPHA_HIGH, like the raster. */
const FADE = `linear-gradient(to right, var(--surface) ${pct(IVT_ALPHA_LOW)}, rgba(0, 0, 0, 0) ${pct(IVT_ALPHA_HIGH)})`;

const COUNT_STOPS = [0, 1, 2, 3, 4].map((i) => `var(--count-${i})`).join(", ");

const VIEWS: { view: IvtView; label: string }[] = [
  { view: "drape", label: es.map.viewDrape },
  { view: "isolines", label: es.map.viewIsolines },
];

/**
 * IVT legend: view toggle, then the color scale (drape) or the contour levels (isolines), and the outline source.
 * With `count` (no event selected) it is the count-map legend instead: what is counted, n events, period and source.
 */
export function MapLegend({
  view,
  onViewChange,
  count = null,
}: {
  view: IvtView;
  onViewChange: (v: IvtView) => void;
  count?: CountInfo | null;
}) {
  const theme = useTheme();
  if (count) {
    const ticks = countTicks(count.max);
    return (
      <div className="map-legend" data-testid="map-legend" role="group" aria-label={es.map.countLabel}>
        <div className="map-legend-title">{es.map.countTitle}</div>
        <div className="map-legend-note">{es.map.countDef}</div>
        {count.max > 0 && (
          <>
            <div
              className="map-legend-bar"
              data-testid="map-legend-count-bar"
              style={{ background: `linear-gradient(to right, ${COUNT_STOPS})` }}
            />
            <div className="map-legend-ticks" data-testid="map-legend-count-ticks">
              {ticks.map((t) => (
                <span key={t} data-value={t} style={{ left: `${(t / count.max) * 100}%` }}>
                  {t}
                </span>
              ))}
            </div>
          </>
        )}
        <div className="map-legend-note" data-testid="map-legend-count-n">{es.map.countEvents(count.n)}</div>
        {count.from && count.to && (
          <div className="map-legend-note" data-testid="map-legend-count-period">
            {es.map.countPeriod(count.from, count.to)}
          </div>
        )}
        <div className="map-legend-source">{es.map.countSource}</div>
        <div className="map-legend-source">{es.map.outlineSource}</div>
      </div>
    );
  }
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
