import type { ArEvent, LayerManifest, PointFeature } from "../api/client";
import { es } from "../i18n/es";
import { formatUtc } from "../layers/arEvents";
import type { CellReading } from "../layers/useArEvents";
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
  return (
    <aside className="shell-inspector" data-testid="inspector">
      {!layer ? (
        <p className="empty">{es.inspector.empty}</p>
      ) : (
        <div className="inspector-body">
          <h2 className="inspector-title">{layer.title}</h2>
          <dl className="inspector-meta" data-testid="inspector-meta">
            <dt>{es.inspector.source}</dt>
            <dd data-testid="inspector-source">{layer.source}</dd>
            <dt>{es.inspector.period}</dt>
            <dd data-testid="inspector-period">{layer.period}</dd>
            <dt>{es.inspector.license}</dt>
            <dd>{layer.license}</dd>
          </dl>
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
                      {es.inspector.point} {f.id}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          {point && (
            <dl className="inspector-point" data-testid="inspector-point">
              <dt>{es.inspector.id}</dt>
              <dd>{point.id}</dd>
              <dt>{es.inspector.lon}</dt>
              <dd>{point.lon}</dd>
              <dt>{es.inspector.lat}</dt>
              <dd>{point.lat}</dd>
              <dt>{es.inspector.value}</dt>
              <dd>{point.value}</dd>
            </dl>
          )}
        </div>
      )}
    </aside>
  );
}

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
  if (!selected) return <p className="empty">{es.events.hint}</p>;
  const f = eventFields(selected);
  return (
    <>
      <h3>{selected.event_id}</h3>
      {loadingFrames && <p className="empty">{es.events.loadingFrames}</p>}
      <dl className="inspector-point" data-testid="inspector-cell">
        <dt>{es.events.cell}</dt>
        {reading ? (
          <>
            <dd data-testid="cell-value">{ivtText(reading.value)}</dd>
            <dd data-testid="cell-where">{cellWhere(reading)}</dd>
          </>
        ) : (
          <dd className="empty">{es.events.cellHint}</dd>
        )}
      </dl>
      <dl className="inspector-point" data-testid="inspector-event">
        <dt>{es.events.start}</dt>
        <dd data-testid="event-start">{f.start}</dd>
        <dt>{es.events.end}</dt>
        <dd>{f.end}</dd>
        <dt>{es.events.duration}</dt>
        <dd>{f.duration}</dd>
        <dt>{es.events.ivtMax}</dt>
        <dd data-testid="event-ivt-max">{f.ivtMax}</dd>
        <dt>{es.events.ivtMaxAt}</dt>
        <dd>{f.ivtMaxAt}</dd>
        <dt>{es.events.deg0lMax}</dt>
        <dd>{f.deg0lMax}</dd>
        <dt>{es.events.deg0lMean}</dt>
        <dd>{f.deg0lMean}</dd>
        <dt>{es.events.rain}</dt>
        <dd>{f.rain}</dd>
        <dt>{es.events.enso}</dt>
        <dd>{f.enso}</dd>
      </dl>
    </>
  );
}
