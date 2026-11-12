import type { ArEvent } from "../api/client";
import { es } from "../i18n/es";
import { formatDate } from "./eventFormat";

interface Props {
  status: "idle" | "loading" | "ready" | "error";
  items: ArEvent[];
  selectedEventId: string | null;
  onSelectEvent: (id: string) => void;
}

/** Third card of the card row: the AR events of the active `events` layer, 48 px rows, count in the title. */
export function EventListCard({ status, items, selectedEventId, onSelectEvent }: Props) {
  return (
    <section className="event-card card tx" data-testid="event-card" aria-labelledby="event-card-title">
      <h2 id="event-card-title" className="card-title">
        {es.events.list} <span className="num card-count" data-testid="event-count">{items.length}</span>
      </h2>
      {status === "loading" && <p className="empty">{es.events.loading}</p>}
      {status === "error" && <p className="empty">{es.events.error}</p>}
      {status === "ready" && items.length === 0 && <p className="empty">{es.events.none}</p>}
      <ul className="event-list" data-testid="event-list" aria-label={es.events.list}>
        {items.map((e) => (
          <li key={e.event_id}>
            <button
              type="button"
              className="event-row"
              data-testid={`event-${e.event_id}`}
              aria-pressed={e.event_id === selectedEventId}
              onClick={() => onSelectEvent(e.event_id)}
            >
              <span className="event-dot" aria-hidden="true" />
              <span className="event-name">{e.event_id}</span>
              <span className="num event-value">
                <span>{e.ivt_max == null ? es.events.noData : `${es.events.ivtShort} ${Math.round(e.ivt_max)}`}</span>
                <span className="event-date">{formatDate(e.start)}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
