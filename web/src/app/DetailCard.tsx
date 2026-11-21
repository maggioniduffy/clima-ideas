import type { ComponentProps } from "react";
import type { FloodStationState } from "../layers/useFloodStation";
import { ConvectionPanel, type ConvectionPanelProps } from "./ConvectionPanel";
import { DebrisPanel, type DebrisPanelProps } from "./DebrisPanel";
import { EnsoPanel } from "./EnsoPanel";
import { FloodStationPanel } from "./FloodStationPanel";

interface Props {
  /** Selected flood station (charts). */
  flood?: FloodStationState | null;
  /** Opened ENSO panel (table); wins over the flood charts. */
  enso?: ComponentProps<typeof EnsoPanel> | null;
  /** Selected convection layer (IDF + replay); shown when there is no ENSO panel or flood station. */
  convection?: ConvectionPanelProps | null;
  /** Selected debris-catchments layer (ranking and catchment panel); shown when nothing above is. */
  debris?: DebrisPanelProps | null;
  /** Opens an AR event (flood tags). */
  onOpenArEvent?: (id: string) => void;
}

/** Second card of the card row: ENSO table or flood-station charts; not rendered when there is nothing to show. */
export function DetailCard({ flood = null, enso = null, convection = null, debris = null, onOpenArEvent }: Props) {
  if (!enso && !flood && !convection && !debris) return null;
  return (
    <section className="detail-card card tx" data-testid="detail-card">
      {enso ? (
        <EnsoPanel {...enso} />
      ) : flood ? (
        <FloodStationPanel state={flood} onOpenArEvent={onOpenArEvent} />
      ) : convection ? (
        <ConvectionPanel {...convection} />
      ) : (
        debris && <DebrisPanel {...debris} />
      )}
    </section>
  );
}
