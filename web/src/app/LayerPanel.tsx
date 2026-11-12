import { Fragment } from "react";
import type { LayerManifest } from "../api/client";
import { es } from "../i18n/es";

interface Props {
  layers: LayerManifest[];
  status: "loading" | "ready" | "error";
  activeIds: ReadonlySet<string>;
  selectedId: string | null;
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
  /** ENSO button of the active `events` layer (the event list itself lives in its own card). */
  events?: {
    layerId: string;
    /** ENSO-phase statistics (F1.8): the button shows unless the layer publishes no report ("none"/absent). */
    ensoStatus?: "none" | "loading" | "ready" | "error";
    ensoOpen?: boolean;
    onToggleEnso?: () => void;
  };
}

export function LayerPanel({ layers, status, activeIds, selectedId, onToggle, onSelect, events }: Props) {
  return (
    <aside className="shell-layers" id="layer-panel" data-testid="layer-panel">
      <h2 className="panel-title">{es.drawers.layers}</h2>
      {status === "loading" && <p className="empty">{es.layers.loading}</p>}
      {status === "error" && <p className="empty">{es.layers.error}</p>}
      {status === "ready" && layers.length === 0 && <p className="empty">{es.layers.empty}</p>}
      <ul className="layer-list">
        {layers.map((l) => {
          const active = activeIds.has(l.id);
          return (
            <Fragment key={l.id}>
              <li
                className="layer-item"
                data-testid={`layer-item-${l.id}`}
                data-active={active}
                data-selected={selectedId === l.id}
              >
                <input
                  type="checkbox"
                  checked={active}
                  aria-label={[es.layers.toggle, l.title].join(" ")}
                  data-testid={`layer-toggle-${l.id}`}
                  onChange={() => onToggle(l.id)}
                />
                <button type="button" className="layer-title" onClick={() => onSelect(l.id)}>
                  {l.title}
                </button>
              </li>
              {active && events?.layerId === l.id && (
                <li className="enso-item">
                  {events.ensoStatus && events.ensoStatus !== "none" && (
                    <button
                      type="button"
                      className="enso-open"
                      data-testid="enso-open"
                      aria-pressed={!!events.ensoOpen}
                      aria-controls="enso-panel"
                      onClick={events.onToggleEnso}
                    >
                      {es.enso.open}
                    </button>
                  )}
                </li>
              )}
            </Fragment>
          );
        })}
      </ul>
    </aside>
  );
}
