import { useMemo, useState } from "react";
import type { ArEvent } from "../api/client";
import { es } from "../i18n/es";
import {
  DEFAULT_TOGGLES,
  SORT_KEYS,
  TOP_N,
  type ArToggles,
  type SortKey,
  groupByYearMonth,
  isMonthOn,
  isYearOn,
  toggleMonth,
  toggleYear,
} from "../layers/arFilter";
import { formatDate } from "./eventFormat";

interface Props {
  status: "idle" | "loading" | "ready" | "error";
  /** All the events of the layer: the year and month tree is built from them. */
  items: ArEvent[];
  /** What the filter leaves (ranked top N when `topOn`); defaults to `items`. */
  shown?: ArEvent[];
  toggles?: ArToggles;
  onTogglesChange?: (t: ArToggles) => void;
  sortKey?: SortKey;
  onSortKeyChange?: (k: SortKey) => void;
  topOn?: boolean;
  onTopOnChange?: (on: boolean) => void;
  topN?: number;
  selectedEventId: string | null;
  onSelectEvent: (id: string) => void;
}

const SORT_LABEL: Record<SortKey, string> = {
  ivt_max: es.events.filter.sortIvt,
  tp_sum_mm: es.events.filter.sortRain,
  duration_h: es.events.filter.sortDuration,
};

function EventRow({ e, selected, onSelect }: { e: ArEvent; selected: boolean; onSelect: (id: string) => void }) {
  return (
    <button
      type="button"
      className="event-row"
      data-testid={`event-${e.event_id}`}
      aria-pressed={selected}
      onClick={() => onSelect(e.event_id)}
    >
      <span className="event-dot" aria-hidden="true" />
      <span className="event-name">{e.event_id}</span>
      <span className="num event-value">
        <span>{e.ivt_max == null ? es.events.noData : `${es.events.ivtShort} ${Math.round(e.ivt_max)}`}</span>
        <span className="event-date">{formatDate(e.start)}</span>
      </span>
    </button>
  );
}

/** A toggle (checkbox) with its count, and a separate disclosure button that opens what is inside. */
function ToggleRow(props: {
  kind: "year" | "month";
  /** "2000" or "2000-03": the tail of the test ids. */
  id: string;
  label: string;
  count: number;
  on: boolean;
  onToggle: () => void;
  expanded?: boolean;
  onExpand?: () => void;
  expandLabel?: string;
}) {
  const { kind, id, label, count, on, onToggle, expanded, onExpand, expandLabel } = props;
  return (
    <div className="ar-row" data-testid={`${kind}-row-${id}`}>
      {onExpand ? (
        <button
          type="button"
          className="ar-expand"
          data-testid={`${kind}-expand-${id}`}
          aria-expanded={!!expanded}
          aria-label={expandLabel}
          onClick={onExpand}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
            <path d="M4 2 L8.5 6 L4 10" fill="none" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        </button>
      ) : (
        <span className="ar-expand-gap" />
      )}
      <label className="ar-toggle">
        <input type="checkbox" data-testid={`${kind}-toggle-${id}`} checked={on} onChange={onToggle} />
        <span className="ar-label">{label}</span>
        <span className="num ar-count">{count}</span>
      </label>
    </div>
  );
}

/**
 * Third card of the card row: the AR events of the active `events` layer as a year → month → event tree
 * (years collapsed, everything on), plus a sort selector and the "top N" switch. Filter state lives in Shell.
 */
export function EventListCard({
  status,
  items,
  shown = items,
  toggles = DEFAULT_TOGGLES,
  onTogglesChange,
  sortKey = "ivt_max",
  onSortKeyChange,
  topOn = false,
  onTopOnChange,
  topN = TOP_N,
  selectedEventId,
  onSelectEvent,
}: Props) {
  const years = useMemo(() => groupByYearMonth(items), [items]);
  const [openYears, setOpenYears] = useState<ReadonlySet<number>>(new Set());
  const [openMonths, setOpenMonths] = useState<ReadonlySet<string>>(new Set());
  const flip = <T,>(s: ReadonlySet<T>, v: T) => {
    const next = new Set(s);
    if (!next.delete(v)) next.add(v);
    return next;
  };
  const shownIds = useMemo(() => new Set(shown.map((e) => e.event_id)), [shown]);
  const mm = (m: number) => String(m).padStart(2, "0");
  const showTree = status === "ready" && items.length > 0;

  return (
    <section className="event-card card tx" data-testid="event-card" aria-labelledby="event-card-title">
      <h2 id="event-card-title" className="card-title">
        {es.events.list} <span className="num card-count" data-testid="event-count">{shown.length}</span>
      </h2>
      {status === "loading" && <p className="empty">{es.events.loading}</p>}
      {status === "error" && <p className="empty">{es.events.error}</p>}
      {status === "ready" && items.length === 0 && <p className="empty">{es.events.none}</p>}
      {showTree && (
        <div className="ar-controls">
          <select
            className="ar-sort"
            data-testid="sort-select"
            aria-label={es.events.filter.sortLabel}
            value={sortKey}
            disabled={!topOn}
            title={topOn ? undefined : es.events.filter.sortHint(topN)}
            aria-describedby={topOn ? undefined : "ar-sort-hint"}
            onChange={(e) => onSortKeyChange?.(e.target.value as SortKey)}
          >
            {SORT_KEYS.map((k) => (
              <option key={k} value={k}>{SORT_LABEL[k]}</option>
            ))}
          </select>
          <button
            type="button"
            className="ar-top"
            data-testid="top-toggle"
            aria-pressed={topOn}
            onClick={() => onTopOnChange?.(!topOn)}
          >
            {es.events.filter.top(topN)}
          </button>
          {!topOn && (
            <small id="ar-sort-hint" className="ar-hint" data-testid="sort-hint">
              {es.events.filter.sortHint(topN)}
            </small>
          )}
        </div>
      )}
      {showTree && shown.length === 0 && <p className="empty">{es.events.filter.noneShown}</p>}
      <div className="event-list" data-testid="event-list" role="group" aria-label={es.events.filter.label}>
        {topOn && showTree && (
          <ul className="ar-top-list" data-testid="top-list" aria-label={es.events.filter.topList}>
            {shown.map((e) => (
              <li key={e.event_id}>
                <EventRow e={e} selected={e.event_id === selectedEventId} onSelect={onSelectEvent} />
              </li>
            ))}
          </ul>
        )}
        {showTree && (
          <ul className="ar-tree">
            {years.map((y) => {
              const open = openYears.has(y.year);
              return (
                <li key={y.year}>
                  <ToggleRow
                    kind="year"
                    id={String(y.year)}
                    label={String(y.year)}
                    count={y.events.length}
                    on={isYearOn(toggles, y.year)}
                    onToggle={() => onTogglesChange?.(toggleYear(toggles, y.year))}
                    expanded={open}
                    onExpand={() => setOpenYears(flip(openYears, y.year))}
                    expandLabel={es.events.filter.yearMonths(y.year)}
                  />
                  {open && (
                    <ul className="ar-months">
                      {y.months.map((m) => {
                        const key = `${y.year}-${m.month}`;
                        const mOpen = !topOn && openMonths.has(key);
                        const name = es.events.filter.months[m.month - 1];
                        return (
                          <li key={key}>
                            <ToggleRow
                              kind="month"
                              id={`${y.year}-${mm(m.month)}`}
                              label={name}
                              count={m.events.length}
                              on={isMonthOn(toggles, y.year, m.month)}
                              onToggle={() => onTogglesChange?.(toggleMonth(toggles, y.year, m.month))}
                              expanded={mOpen}
                              onExpand={topOn ? undefined : () => setOpenMonths(flip(openMonths, key))}
                              expandLabel={es.events.filter.monthEvents(name, y.year)}
                            />
                            {mOpen && (
                              <ul className="ar-events">
                                {m.events
                                  .filter((e) => shownIds.has(e.event_id))
                                  .map((e) => (
                                    <li key={e.event_id}>
                                      <EventRow e={e} selected={e.event_id === selectedEventId} onSelect={onSelectEvent} />
                                    </li>
                                  ))}
                              </ul>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
