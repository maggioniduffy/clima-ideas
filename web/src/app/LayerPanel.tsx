import type { LayerManifest } from "../api/client";
import { es } from "../i18n/es";
import { isReliefLayer } from "../layers/useLayers";

interface Props {
  layers: LayerManifest[];
  status: "loading" | "ready" | "error";
  activeIds: ReadonlySet<string>;
  selectedId: string | null;
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
}

/**
 * Layer list of the menu: one row per layer, a label around a visible checkbox; several layers can be on. Relief layers
 * are not listed (the map background control owns them).
 * Choosing a layer that is on but not selected selects it (its short name shows in the menu pill and its panel opens);
 * choosing the selected one, or one that is off, toggles it (turning a layer on also selects it).
 */
export function LayerPanel({ layers, status, activeIds, selectedId, onToggle, onSelect }: Props) {
  const listed = layers.filter((l) => !isReliefLayer(l));
  return (
    <nav className="layer-list-nav" id="layer-panel" data-testid="layer-panel" aria-label={es.drawers.layers}>
      {status === "loading" && <p className="empty">{es.layers.loading}</p>}
      {status === "error" && <p className="empty">{es.layers.error}</p>}
      {status === "ready" && listed.length === 0 && <p className="empty">{es.layers.empty}</p>}
      {listed.map((l) => {
        const active = activeIds.has(l.id);
        return (
          <label
            key={l.id}
            className="layer-row"
            title={l.title}
            data-testid={`layer-item-${l.id}`}
            data-active={active}
            data-selected={selectedId === l.id}
          >
            <input
              type="checkbox"
              className="layer-row-input"
              checked={active}
              aria-label={[es.layers.toggle, l.title].join(" ")}
              data-testid={`layer-toggle-${l.id}`}
              onChange={() => (active && selectedId !== l.id ? onSelect(l.id) : onToggle(l.id))}
            />
            <span className="layer-row-title">{es.layers.short[l.id] ?? l.title}</span>
          </label>
        );
      })}
    </nav>
  );
}
