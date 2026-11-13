import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { vi } from "vitest";
import type { ArEvent } from "../api/client";
import { DEFAULT_TOGGLES, TOP_N, type ArToggles, type SortKey, visibleEvents } from "../layers/arFilter";
import { es } from "../i18n/es";
import { EventListCard } from "./EventListCard";

const ev = (id: string, start: string, o: Partial<ArEvent> = {}) =>
  ({ event_id: id, start, ivt_max: 300, tp_sum_mm: 10, duration_h: 6, ...o }) as ArEvent;

const items = [
  ev("AR-2000-001", "2000-03-10T06:00:00Z", { ivt_max: 350, tp_sum_mm: 20, duration_h: 12 }),
  ev("AR-2000-002", "2000-07-21T00:00:00Z", { ivt_max: null, tp_sum_mm: 90, duration_h: 30 }),
  ev("AR-2001-001", "2001-03-02T00:00:00Z", { ivt_max: 800, tp_sum_mm: 5, duration_h: 48 }),
];
const base = { status: "ready" as const, items, selectedEventId: "AR-2000-002" };

/** The card is controlled by Shell; this harness plays that part with the real filter helpers. */
function Harness({ onSelectEvent = vi.fn(), all = items }: { onSelectEvent?: (id: string) => void; all?: ArEvent[] }) {
  const [toggles, setToggles] = useState<ArToggles>(DEFAULT_TOGGLES);
  const [sortKey, setSortKey] = useState<SortKey>("ivt_max");
  const [topOn, setTopOn] = useState(false);
  const v = visibleEvents(all, toggles, sortKey, topOn, 2);
  return (
    <EventListCard
      {...base}
      items={all}
      shown={v.events}
      toggles={toggles}
      onTogglesChange={setToggles}
      sortKey={sortKey}
      onSortKeyChange={setSortKey}
      topOn={topOn}
      onTopOnChange={setTopOn}
      topN={2}
      onSelectEvent={onSelectEvent}
    />
  );
}
const expandYear = (y: number) => fireEvent.click(screen.getByTestId(`year-expand-${y}`));
const expandMonth = (y: number, m: string) => fireEvent.click(screen.getByTestId(`month-expand-${y}-${m}`));

test("years start collapsed and on, each showing its event count", () => {
  render(<Harness />);
  expect(screen.getByTestId("year-toggle-2000")).toBeChecked();
  expect(screen.getByTestId("year-toggle-2000")).toHaveAccessibleName(/2000/);
  expect(screen.getByTestId("year-row-2000")).toHaveTextContent("2");
  expect(screen.getByTestId("year-row-2001")).toHaveTextContent("1");
  expect(screen.getByTestId("year-expand-2000")).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByTestId("month-toggle-2000-03")).toBeNull();
  expect(screen.queryByTestId("event-AR-2000-001")).toBeNull();
});

test("expanding a year shows only its months with events, as toggles with counts; no year-by-month grid", () => {
  render(<Harness />);
  expandYear(2000);
  expect(screen.getByTestId("year-expand-2000")).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByTestId("month-toggle-2000-03")).toBeChecked();
  expect(screen.getByTestId("month-toggle-2000-07")).toBeChecked();
  expect(screen.queryByTestId("month-toggle-2000-04")).toBeNull();
  expect(screen.queryByTestId("month-toggle-2001-03")).toBeNull(); // other year still collapsed
  expect(screen.getByTestId("month-row-2000-03")).toHaveTextContent("marzo");
});

test("expanding a month lists its events; selecting one reports it and marks the selected row", () => {
  const onSelectEvent = vi.fn();
  render(<Harness onSelectEvent={onSelectEvent} />);
  expandYear(2000);
  expandMonth(2000, "03");
  expect(screen.getByTestId("event-AR-2000-001")).toHaveTextContent("2000-03-10");
  expect(screen.getByTestId("event-AR-2000-001")).toHaveTextContent("IVT 350");
  expect(screen.getByTestId("event-AR-2000-001")).toHaveAttribute("aria-pressed", "false");
  expandMonth(2000, "07");
  expect(screen.getByTestId("event-AR-2000-002")).toHaveTextContent(es.events.noData);
  expect(screen.getByTestId("event-AR-2000-002")).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByTestId("event-AR-2000-001"));
  expect(onSelectEvent).toHaveBeenCalledWith("AR-2000-001");
});

test("the year toggle removes all of its events from the list and the count; the month toggle only that month", () => {
  render(<Harness />);
  expect(screen.getByTestId("event-count")).toHaveTextContent("3");
  fireEvent.click(screen.getByTestId("year-toggle-2001"));
  expect(screen.getByTestId("year-toggle-2001")).not.toBeChecked();
  expect(screen.getByTestId("event-count")).toHaveTextContent("2");
  fireEvent.click(screen.getByTestId("year-toggle-2001"));
  expandYear(2000);
  fireEvent.click(screen.getByTestId("month-toggle-2000-03"));
  expect(screen.getByTestId("month-toggle-2000-03")).not.toBeChecked();
  expect(screen.getByTestId("year-toggle-2000")).toBeChecked();
  expect(screen.getByTestId("month-toggle-2000-07")).toBeChecked();
  expect(screen.getByTestId("event-count")).toHaveTextContent("2"); // 3 minus the March event
  expandMonth(2000, "07");
  expect(screen.getByTestId("event-AR-2000-002")).toBeInTheDocument();
});

test("top N shows a flat ranked list of the N highest by the chosen key, among the filtered events", () => {
  render(<Harness />);
  const top = screen.getByTestId("top-toggle");
  expect(top).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(top);
  expect(top).toHaveAttribute("aria-pressed", "true");
  const ranked = () => within(screen.getByTestId("top-list")).getAllByRole("button").map((b) => b.getAttribute("data-testid"));
  expect(ranked()).toEqual(["event-AR-2001-001", "event-AR-2000-001"]); // by IVT, missing last
  fireEvent.change(screen.getByTestId("sort-select"), { target: { value: "tp_sum_mm" } });
  expect(ranked()).toEqual(["event-AR-2000-002", "event-AR-2000-001"]);
  fireEvent.change(screen.getByTestId("sort-select"), { target: { value: "duration_h" } });
  expect(ranked()).toEqual(["event-AR-2001-001", "event-AR-2000-002"]);
  fireEvent.click(screen.getByTestId("year-toggle-2001"));
  expect(ranked()).toEqual(["event-AR-2000-002", "event-AR-2000-001"]);
  expect(screen.getByTestId("event-count")).toHaveTextContent("2");
  fireEvent.click(top);
  expect(screen.queryByTestId("top-list")).toBeNull();
});

test("the sort selector offers IVT, rain and duration, and the top switch names N", () => {
  render(<Harness />);
  const options = within(screen.getByTestId("sort-select")).getAllByRole("option").map((o) => o.textContent);
  expect(options).toEqual([es.events.filter.sortIvt, es.events.filter.sortRain, es.events.filter.sortDuration]);
  expect(screen.getByTestId("top-toggle")).toHaveTextContent(es.events.filter.top(2));
  expect(TOP_N).toBeGreaterThan(0);
});

test("the title carries the event count", () => {
  render(<Harness />);
  expect(screen.getByRole("heading", { name: `${es.events.list} 3` })).toBeInTheDocument();
});

test("loading, error and empty states", () => {
  const props = { ...base, items: [], onSelectEvent: vi.fn() };
  const { rerender } = render(<EventListCard {...props} status="loading" />);
  expect(screen.getByText(es.events.loading)).toBeInTheDocument();
  rerender(<EventListCard {...props} status="error" />);
  expect(screen.getByText(es.events.error)).toBeInTheDocument();
  rerender(<EventListCard {...props} />);
  expect(screen.getByText(es.events.none)).toBeInTheDocument();
});

test("the response sort key is offered only when responses are loaded and ranks by the given ratios", () => {
  const { rerender } = render(<EventListCard {...base} onSelectEvent={vi.fn()} />);
  const opts = () => within(screen.getByTestId("sort-select")).getAllByRole("option").map((o) => o.textContent);
  expect(opts()).not.toContain(es.events.filter.sortResponse);
  rerender(<EventListCard {...base} hasResponses onSelectEvent={vi.fn()} />);
  expect(opts()).toEqual([
    es.events.filter.sortIvt, es.events.filter.sortRain, es.events.filter.sortDuration, es.events.filter.sortResponse,
  ]);
});
