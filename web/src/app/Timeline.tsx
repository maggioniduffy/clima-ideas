import { useMemo } from "react";
import type { ArEvent } from "../api/client";
import { es } from "../i18n/es";
import { eventDomain, eventSpans, fractionOf, formatUtc, periodDomain } from "../layers/arEvents";
import type { ArEventsState } from "../layers/useArEvents";

interface Props {
  events?: ArEvent[];
  period?: string;
  selectedEventId?: string | null;
  onSelectEvent?: (id: string) => void;
  /** Replay state of the selected event; null when nothing is selected. */
  replay?: ArEventsState | null;
}

const pct = (f: number) => `${(f * 100).toFixed(3)}%`;

export function Timeline({ events = [], period, selectedEventId = null, onSelectEvent, replay = null }: Props) {
  const domain = useMemo(() => (period ? periodDomain(period) : null), [period]);
  const spans = useMemo(() => (domain ? eventSpans(events, domain) : []), [events, domain]);
  const selected = replay?.selectedEvent ?? null;
  const detail = selected ? eventDomain(selected) : null;

  if (!domain || events.length === 0) {
    return (
      <footer className="shell-timeline" data-testid="timeline">
        <p className="empty">{es.timeline.empty}</p>
      </footer>
    );
  }

  return (
    <footer className="shell-timeline" data-testid="timeline">
      {replay && selected && (
        <div className="replay-controls" data-testid="replay-controls" data-frame={replay.frame} data-playing={replay.playing}>
          <button type="button" data-testid="replay-back" aria-label={es.events.stepBack} onClick={() => replay.step(-1)}>
            {es.events.icons.back}
          </button>
          <button
            type="button"
            data-testid="replay-play"
            aria-label={replay.playing ? es.events.pause : es.events.play}
            aria-pressed={replay.playing}
            onClick={replay.toggle}
          >
            {replay.playing ? es.events.icons.pause : es.events.icons.play}
          </button>
          <button type="button" data-testid="replay-forward" aria-label={es.events.stepForward} onClick={() => replay.step(1)}>
            {es.events.icons.forward}
          </button>
          <input
            type="range"
            data-testid="replay-slider"
            aria-label={es.events.hour}
            min={0}
            max={Math.max(replay.nFrames - 1, 0)}
            value={replay.frame}
            disabled={replay.nFrames === 0}
            onChange={(e) => replay.seek(Number(e.target.value))}
          />
          <span className="replay-time" data-testid="replay-time">
            {replay.cursorMs != null && formatUtc(replay.cursorMs)}
          </span>
        </div>
      )}
      <div className="timeline-track" data-testid="timeline-track" aria-label={es.timeline.events}>
        {spans.map((sp) => (
          <button
            key={sp.id}
            type="button"
            className="timeline-mark"
            data-testid={`timeline-event-${sp.id}`}
            aria-pressed={sp.id === selectedEventId}
            aria-label={sp.id}
            style={{ left: pct(sp.left), width: pct(sp.width), background: sp.color }}
            onClick={() => onSelectEvent?.(sp.id)}
          />
        ))}
        {replay?.cursorMs != null && (
          <div
            className="timeline-cursor"
            data-testid="timeline-cursor"
            data-frame={replay.frame}
            aria-label={es.timeline.cursor}
            style={{ left: pct(fractionOf(replay.cursorMs, domain)) }}
          />
        )}
      </div>
      {detail && replay?.cursorMs != null && (
        <div className="timeline-detail" data-testid="timeline-detail">
          <div className="timeline-span" />
          <div
            className="timeline-cursor"
            data-testid="timeline-detail-cursor"
            style={{ left: pct(fractionOf(replay.cursorMs, detail)) }}
          />
        </div>
      )}
    </footer>
  );
}
