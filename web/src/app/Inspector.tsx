import type { LayerManifest, PointFeature } from "../api/client";
import { es } from "../i18n/es";

interface Props {
  layer: LayerManifest | null;
  features: PointFeature[];
  selectedPointId: string | null;
  onSelectPoint: (id: string) => void;
}

export function Inspector({ layer, features, selectedPointId, onSelectPoint }: Props) {
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
