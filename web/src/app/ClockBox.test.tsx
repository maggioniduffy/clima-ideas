import { render, screen } from "@testing-library/react";
import { es } from "../i18n/es";
import { ClockBox } from "./ClockBox";

test("shows the replay timestamp and the hour counter", () => {
  render(<ClockBox cursorMs={Date.parse("2000-03-10T07:00:00Z")} frame={1} nFrames={4} />);
  expect(screen.getByTestId("map-clock")).toHaveTextContent("2000-03-10 07:00 UTC");
  expect(screen.getByTestId("map-clock")).toHaveTextContent(es.events.clockHour(2, 4));
});
