import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { es } from "../i18n/es";
import { EventListCard } from "./EventListCard";

const items = [
  { event_id: "AR-2000-001", start: "2000-03-10T06:00:00Z", ivt_max: 350 },
  { event_id: "AR-2000-002", start: "2000-07-21T00:00:00Z", ivt_max: null },
] as never;
const base = { status: "ready" as const, items, selectedEventId: "AR-2000-002" };

test("lists events with date and IVT, marks the selected one and reports selection", () => {
  const onSelectEvent = vi.fn();
  render(<EventListCard {...base} onSelectEvent={onSelectEvent} />);
  expect(screen.getByTestId("event-AR-2000-001")).toHaveTextContent("2000-03-10");
  expect(screen.getByTestId("event-AR-2000-001")).toHaveTextContent("IVT 350");
  expect(screen.getByTestId("event-AR-2000-002")).toHaveTextContent(es.events.noData);
  expect(screen.getByTestId("event-AR-2000-002")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("event-AR-2000-001")).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(screen.getByTestId("event-AR-2000-001"));
  expect(onSelectEvent).toHaveBeenCalledWith("AR-2000-001");
});

test("the title carries the event count", () => {
  render(<EventListCard {...base} onSelectEvent={vi.fn()} />);
  expect(screen.getByRole("heading", { name: `${es.events.list} 2` })).toBeInTheDocument();
  expect(screen.getByTestId("event-count")).toHaveTextContent("2");
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
