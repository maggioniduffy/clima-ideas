import { es } from "../i18n/es";
import { formatUtc } from "../layers/arEvents";

/** Top-right box over the map while a replay is active: the replay timestamp and the hour counter. */
export function ClockBox({ cursorMs, frame, nFrames }: { cursorMs: number; frame: number; nFrames: number }) {
  return (
    <div className="map-clock" data-testid="map-clock">
      <div className="num map-clock-time">{formatUtc(cursorMs)}</div>
      <div className="num map-clock-hour">{es.events.clockHour(frame + 1, nFrames)}</div>
    </div>
  );
}
