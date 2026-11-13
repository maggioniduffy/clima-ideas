import type { ArEvent, FloodStationFeature, LayerManifest, PointFeature } from "../api/client";
import { es } from "../i18n/es";
import { formatUtc } from "../layers/arEvents";
import type { CellReading } from "../layers/useArEvents";
import { FLOOD_LAYER_ID } from "../layers/useFloodStation";
import { eventFields, formatLatLon, ivtText } from "./eventFormat";

interface Props {
  layer: LayerManifest | null;
  features: PointFeature[];
  selectedPointId: string | null;
  onSelectPoint: (id: string) => void;
  /** Selected AR event and the IVT cell under the cursor (kind "events" layers). */
  event?: { selected: ArEvent | null; loadingFrames: boolean; reading: CellReading | null };
}

export function Inspector({ layer, features, selectedPointId, onSelectPoint, event }: Props) {
  const point = features.find((f) => f.id === selectedPointId) ?? null;
  const isFlood = layer?.id === FLOOD_LAYER_ID;
  return (
    <aside className="shell-inspector card tx" id="inspector-panel" data-testid="inspector">
      {!layer ? (
        <p className="empty">{es.inspector.empty}</p>
      ) : (
        <div className="inspector-body">
          <h2 className="inspector-title">{layer.title}</h2>
          {layer.kind === "events" && <EventDetails {...(event ?? { selected: null, loadingFrames: false, reading: null })} />}
          {features.length > 0 && (
            <>
              <h3>{es.inspector.points}</h3>
              <ul className="feature-list" data-testid="feature-list">
                {features.map((f) => (
                  <li key={f.id}>
                    <button
                      type="button"
                      data-testid={`feature-${f.id}`}
                      aria-pressed={f.id === selectedPointId}
                      onClick={() => onSelectPoint(f.id)}
                    >
                      {isFlood ? stationLabel(f) : `${es.inspector.point} ${f.id}`}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          {!isFlood && point && (
            <dl className="inspector-point" data-testid="inspector-point">
              <dt>{es.inspector.id}</dt>
              <dd className="num">{point.id}</dd>
              <dt>{es.inspector.lon}</dt>
              <dd className="num">{point.lon}</dd>
              <dt>{es.inspector.lat}</dt>
              <dd className="num">{point.lat}</dd>
              <dt>{es.inspector.value}</dt>
              <dd className="num">{point.value}</dd>
            </dl>
          )}
          <dl className="inspector-meta kv" data-testid="inspector-meta">
            <dt>{es.inspector.source}</dt>
            <dd className="num" data-testid="inspector-source">{layer.source}</dd>
            <dt>{es.inspector.period}</dt>
            <dd className="num" data-testid="inspector-period">{layer.period}</dd>
            <dt>{es.inspector.license}</dt>
            <dd className="num">{layer.license}</dd>
          </dl>
        </div>
      )}
    </aside>
  );
}

const stationLabel = (f: PointFeature) => {
  const s = f as FloodStationFeature;
  return [s.name ?? f.id, s.river].filter(Boolean).join(es.events.sep);
};

const cellWhere = (r: CellReading) => [formatLatLon(r.lat, r.lon), formatUtc(r.timeMs)].join(es.events.sep);

function EventDetails({
  selected,
  loadingFrames,
  reading,
}: {
  selected: ArEvent | null;
  loadingFrames: boolean;
  reading: CellReading | null;
}) {
  if (!selected)
    return (
      <div className="events-help" data-testid="events-help">
        <p className="events-hint">{es.events.hint}</p>
        <details>
          <summary>{es.events.help.title}</summary>
          <p>{es.events.help.ar}</p>
          <p>{es.events.help.ivt}</p>
          <p>{es.events.help.events}</p>
        </details>
      </div>
    );
  const f = eventFields(selected);
  return (
    <>
      <p className="inspector-sub">{selected.event_id}</p>
      <dl className="inspector-point kv" data-testid="inspector-event">
        <dt>{es.events.start}</dt>
        <dd className="num" data-testid="event-start">{f.start}</dd>
        <dt>{es.events.end}</dt>
        <dd className="num">{f.end}</dd>
        <dt>{es.events.duration}</dt>
        <dd className="num">{f.duration}</dd>
        <dt>{es.events.ivtMax}</dt>
        <dd className="num" data-testid="event-ivt-max">{f.ivtMax}</dd>
        <dt className="kv-wide">{es.events.ivtMaxAt}</dt>
        <dd className="num kv-wide">{f.ivtMaxAt}</dd>
        <dt>{es.events.deg0lMax}</dt>
        <dd className="num">{f.deg0lMax}</dd>
        <dt>{es.events.deg0lMean}</dt>
        <dd className="num">{f.deg0lMean}</dd>
        <dt>{es.events.rain}</dt>
        <dd className="num">{f.rain}</dd>
        <dt>{es.events.enso}</dt>
        <dd className="num">{f.enso}</dd>
      </dl>
      {loadingFrames && <p className="empty">{es.events.loadingFrames}</p>}
      <p className="empty" data-testid="event-core-note">{es.events.coreNote}</p>
      <dl className="inspector-point kv" data-testid="inspector-cell">
        <dt>{reading?.kind === "max" ? es.events.cellMax : es.events.cell}</dt>
        {reading ? (
          <dd className="num" data-testid="cell-value">{ivtText(reading.value)}</dd>
        ) : (
          <dd className="empty kv-wide">{es.events.cellHint}</dd>
        )}
        {reading && (
          <dd className="num kv-wide" data-testid="cell-where">
            {reading.kind === "max" ? formatLatLon(reading.lat, reading.lon) : cellWhere(reading)}
          </dd>
        )}
      </dl>
    </>
  );
}
