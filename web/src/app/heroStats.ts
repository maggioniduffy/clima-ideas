import { es } from "../i18n/es";

export interface HeroStat {
  id: string;
  value: number;
  caption: string;
}

/** What the selected layer's panel already computes; every field is optional and absent when it is not available. */
export interface HeroInput {
  /** Selected events layer: events left by the filter and in the whole layer. */
  events?: { shown: number; total: number };
  /** Selected points layer: how many points the inspector lists; `station` picks the flood-station caption. */
  points?: { count: number; station: boolean };
  /** Selected catchments layer: catchments drawn on the map. */
  catchments?: number;
}

/** Up to 3 big numbers for the hero row, in a fixed order; nothing is invented, so no input means no numbers. */
export function heroStats({ events, points, catchments }: HeroInput): HeroStat[] {
  const out: HeroStat[] = [];
  if (events) {
    out.push({ id: "events-shown", value: events.shown, caption: es.hero.eventsShown });
    out.push({ id: "events-total", value: events.total, caption: es.hero.eventsTotal });
  }
  if (points && points.count > 0)
    out.push({ id: "points", value: points.count, caption: points.station ? es.hero.stations : es.hero.points });
  if (catchments != null) out.push({ id: "catchments", value: catchments, caption: es.hero.catchments });
  return out.slice(0, 3);
}
