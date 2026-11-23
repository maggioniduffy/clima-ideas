import type { LayerManifest } from "../api/client";
import { es } from "../i18n/es";

interface Props {
  layers: LayerManifest[];
  status: "loading" | "ready" | "error";
  activeIds: ReadonlySet<string>;
  selectedId: string | null;
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
}

/**
 * Layer pills of the header. Each pill is a label around the visually hidden checkbox; several layers can be on.
 * Choosing a layer that is on but not selected selects it (its title and numbers show in the hero); choosing the
 * selected one, or one that is off, toggles it (turning a layer on also selects it).
 */
export function LayerPanel({ layers, status, activeIds, selectedId, onToggle, onSelect }: Props) {
  return (
    <nav className="layer-pills" id="layer-panel" data-testid="layer-panel" aria-label={es.drawers.layers}>
      {status === "loading" && <p className="empty">{es.layers.loading}</p>}
      {status === "error" && <p className="empty">{es.layers.error}</p>}
      {status === "ready" && layers.length === 0 && <p className="empty">{es.layers.empty}</p>}
      {layers.map((l) => {
        const active = activeIds.has(l.id);
        return (
          <label
            key={l.id}
            className="layer-pill"
            title={l.title}
            data-testid={`layer-item-${l.id}`}
            data-active={active}
            data-selected={selectedId === l.id}
          >
            <input
              type="checkbox"
              className="layer-pill-input"
              checked={active}
              aria-label={[es.layers.toggle, l.title].join(" ")}
              data-testid={`layer-toggle-${l.id}`}
              onChange={() => (active && selectedId !== l.id ? onSelect(l.id) : onToggle(l.id))}
            />
            <span className="layer-pill-title">{es.layers.short[l.id] ?? l.title}</span>
          </label>
        );
      })}
    </nav>
  );
}
