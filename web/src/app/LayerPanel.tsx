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

export function LayerPanel({ layers, status, activeIds, selectedId, onToggle, onSelect }: Props) {
  return (
    <aside className="shell-layers" data-testid="layer-panel">
      {status === "loading" && <p className="empty">{es.layers.loading}</p>}
      {status === "error" && <p className="empty">{es.layers.error}</p>}
      {status === "ready" && layers.length === 0 && <p className="empty">{es.layers.empty}</p>}
      <ul className="layer-list">
        {layers.map((l) => {
          const active = activeIds.has(l.id);
          return (
            <li
              key={l.id}
              className="layer-item"
              data-testid={`layer-item-${l.id}`}
              data-active={active}
              data-selected={selectedId === l.id}
            >
              <input
                type="checkbox"
                checked={active}
                aria-label={[es.layers.toggle, l.title].join(" ")}
                data-testid={`layer-toggle-${l.id}`}
                onChange={() => onToggle(l.id)}
              />
              <button type="button" className="layer-title" onClick={() => onSelect(l.id)}>
                {l.title}
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
