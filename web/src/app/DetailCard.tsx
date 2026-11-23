import type { ComponentProps } from "react";
import type { FloodStationState } from "../layers/useFloodStation";
import { ConvectionPanel, type ConvectionPanelProps } from "./ConvectionPanel";
import { DebrisPanel, type DebrisPanelProps } from "./DebrisPanel";
import { EnsoPanel } from "./EnsoPanel";
import { FloodStationPanel } from "./FloodStationPanel";
import { ForecastPanel, type ForecastPanelProps } from "./ForecastPanel";
import { HindcastPanel, type HindcastPanelProps } from "./HindcastPanel";

interface Props {
  /** Selected flood station (charts). */
  flood?: FloodStationState | null;
  /** Opened ENSO panel (table); wins over the flood charts. */
  enso?: ComponentProps<typeof EnsoPanel> | null;
  /** Selected convection layer (IDF + replay); shown when there is no ENSO panel or flood station. */
  convection?: ConvectionPanelProps | null;
  /** Selected debris-catchments layer (ranking and catchment panel); shown when nothing above is. */
  debris?: DebrisPanelProps | null;
  /** Selected hindcast-verification layer; shown when nothing above is. */
  hindcast?: HindcastPanelProps | null;
  /** Selected forecast-outlook layer; shown when nothing above is. */
  forecast?: ForecastPanelProps | null;
  /** Opens an AR event (flood tags). */
  onOpenArEvent?: (id: string) => void;
}

/** Second card of the card row: ENSO table or flood-station charts; not rendered when there is nothing to show. */
export function DetailCard({ flood = null, enso = null, convection = null, debris = null, hindcast = null, forecast = null, onOpenArEvent }: Props) {
  if (!enso && !flood && !convection && !debris && !hindcast && !forecast) return null;
  // The forecast / model card keeps its data-tone marker (tests, styling hooks) but follows the theme like every other card.
  const inverse = !enso && !flood && !convection && !debris && !hindcast && !!forecast;
  return (
    <section className="detail-card card" data-testid="detail-card" data-tone={inverse ? "inverse" : undefined}>
      {enso ? (
        <EnsoPanel {...enso} />
      ) : flood ? (
        <FloodStationPanel state={flood} onOpenArEvent={onOpenArEvent} />
      ) : convection ? (
        <ConvectionPanel {...convection} />
      ) : (
        debris ? <DebrisPanel {...debris} /> : hindcast ? <HindcastPanel {...hindcast} /> : forecast && <ForecastPanel {...forecast} />
      )}
    </section>
  );
}
