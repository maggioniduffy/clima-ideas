import { Fragment } from "react";
import type { ArEvent, LayerManifest } from "../api/client";
import { es } from "../i18n/es";
import { formatDate } from "./eventFormat";

interface Props {
  layers: LayerManifest[];
  status: "loading" | "ready" | "error";
  activeIds: ReadonlySet<string>;
  selectedId: string | null;
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
  /** Event list of the active `events` layer (AR replay). */
  events?: {
    layerId: string;
    status: "idle" | "loading" | "ready" | "error";
    items: ArEvent[];
    selectedEventId: string | null;
    onSelectEvent: (id: string) => void;
  };
}

export function LayerPanel({ layers, status, activeIds, selectedId, onToggle, onSelect, events }: Props) {
  return (
    <aside className="shell-layers" id="layer-panel" data-testid="layer-panel">
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
                <li className="event-list-item">
                  {events.status === "loading" && <p className="empty">{es.events.loading}</p>}
                  {events.status === "error" && <p className="empty">{es.events.error}</p>}
                  {events.status === "ready" && events.items.length === 0 && <p className="empty">{es.events.none}</p>}
                  <ul className="event-list" data-testid="event-list" aria-label={es.events.list}>
                    {events.items.map((e) => (
                      <li key={e.event_id}>
                        <button
                          type="button"
                          data-testid={`event-${e.event_id}`}
                          aria-pressed={e.event_id === events.selectedEventId}
                          onClick={() => events.onSelectEvent(e.event_id)}
                        >
                          <span>{formatDate(e.start)}</span>
                          <span className="event-ivt">{e.ivt_max == null ? es.events.noData : `${es.events.ivtShort} ${Math.round(e.ivt_max)}`}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </li>
              )}
            </Fragment>
          );
        })}
      </ul>
    </aside>
  );
}
