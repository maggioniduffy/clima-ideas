import { es } from "../i18n/es";

export function LayerPanel() {
  return (
    <aside className="shell-layers" data-testid="layer-panel">
      <p className="empty">{es.layers.empty}</p>
    </aside>
  );
}
