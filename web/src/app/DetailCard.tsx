import type { ComponentProps } from "react";
import type { FloodStationState } from "../layers/useFloodStation";
import { EnsoPanel } from "./EnsoPanel";
import { FloodStationPanel } from "./FloodStationPanel";

interface Props {
  /** Selected flood station (charts). */
  flood?: FloodStationState | null;
  /** Opened ENSO panel (table); wins over the flood charts. */
  enso?: ComponentProps<typeof EnsoPanel> | null;
}

/** Second card of the card row: ENSO table or flood-station charts; not rendered when there is nothing to show. */
export function DetailCard({ flood = null, enso = null }: Props) {
  if (!enso && !flood) return null;
  return (
    <section className="detail-card card tx" data-testid="detail-card">
      {enso ? <EnsoPanel {...enso} /> : flood && <FloodStationPanel state={flood} />}
    </section>
  );
}
