import { es } from "../i18n/es";
import type { HeroStat } from "./heroStats";

interface Props {
  /** Title of the selected layer (the page name while none is selected). */
  title: string;
  stats?: HeroStat[];
  /** Source and period of the selected layer; shown only next to numbers. */
  source?: { source: string; period: string } | null;
}

/** Hero row: the page `h1` on the left, up to 3 big numbers with a caption and one source line on the right. */
export function Hero({ title, stats = [], source = null }: Props) {
  return (
    <section className="hero" data-testid="hero" aria-label={title}>
      <h1>{title}</h1>
      {stats.length > 0 && (
        <div className="hero-stats" data-testid="hero-stats">
          <ul className="hero-numbers">
            {stats.map((s) => (
              <li key={s.id} data-testid={`hero-stat-${s.id}`}>
                <span className="big-num">{s.value.toLocaleString("es-AR")}</span>
                <span className="big-caption">{s.caption}</span>
              </li>
            ))}
          </ul>
          {source && (
            <p className="hero-source" data-testid="hero-source">
              {es.hero.sourcePeriod(source.source, source.period)}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
