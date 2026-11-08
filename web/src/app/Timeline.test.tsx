import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import type { ArEvent } from "../api/client";
import { ivtColor, rgbCss } from "../layers/arEvents";
import { getTheme } from "../theme/themeStore";
import { es } from "../i18n/es";
import type { ArEventsState } from "../layers/useArEvents";
import { Timeline } from "./Timeline";

const ev = (id: string, start: string, end: string, ivt: number): ArEvent => ({
  event_id: id, start, end, duration_h: 6, n_steps: 1, prob_max: 0.8, area_frac_max: 0.5, ivt_max: ivt,
  ivt_max_time: null, ivt_max_lat: null, ivt_max_lon: null, deg0l_max: null, deg0l_mean: null, tp_sum_mm: null,
  enso_phase: null,
}); // fmt: skip

const events = [
  ev("a", "2000-01-02T00:00:00Z", "2000-01-02T12:00:00Z", 0),
  ev("b", "2000-01-03T00:00:00Z", "2000-01-03T06:00:00Z", 800),
];

test("shows the empty message without events", () => {
  render(<Timeline period="2000-01-01/2000-01-03" />);
  expect(screen.getByText(es.timeline.empty)).toBeInTheDocument();
});

test("draws one colored mark per event and reports clicks", () => {
  const onSelectEvent = vi.fn();
  render(<Timeline events={events} period="2000-01-01/2000-01-03" selectedEventId="b" onSelectEvent={onSelectEvent} />);
  const a = screen.getByTestId("timeline-event-a");
  expect(a.style.left).toBe("33.333%");
  expect(a.style.background).toBe(rgbCss(ivtColor(0, getTheme())));
  expect(screen.getByTestId("timeline-event-b").style.background).toBe(rgbCss(ivtColor(800, getTheme())));
  expect(screen.getByTestId("timeline-event-b")).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByTestId("replay-controls")).toBeNull();
  fireEvent.click(a);
  expect(onSelectEvent).toHaveBeenCalledWith("a");
});

test("replay controls drive the callbacks and the cursor follows the replay time", () => {
  const replay = {
    selectedEvent: events[1],
    frame: 3,
    nFrames: 6,
    playing: false,
    cursorMs: Date.parse("2000-01-03T03:00:00Z"),
    toggle: vi.fn(),
    step: vi.fn(),
    seek: vi.fn(),
  } as unknown as ArEventsState;
  render(<Timeline events={events} period="2000-01-01/2000-01-03" selectedEventId="b" replay={replay} />);
  expect(screen.getByTestId("replay-controls")).toHaveAttribute("data-frame", "3");
  expect(screen.getByTestId("replay-time")).toHaveTextContent("2000-01-03 03:00 UTC");
  expect(screen.getByTestId("timeline-detail-cursor").style.left).toBe("50%");
  fireEvent.click(screen.getByRole("button", { name: es.events.play }));
  expect(replay.toggle).toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: es.events.stepBack }));
  expect(replay.step).toHaveBeenCalledWith(-1);
  fireEvent.click(screen.getByRole("button", { name: es.events.stepForward }));
  expect(replay.step).toHaveBeenCalledWith(1);
  fireEvent.change(screen.getByRole("slider", { name: es.events.hour }), { target: { value: "5" } });
  expect(replay.seek).toHaveBeenCalledWith(5);
});
