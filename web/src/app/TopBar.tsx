import { es } from "../i18n/es";
import { ThemeToggle } from "./ThemeToggle";

export type Drawer = "layers" | "inspector";

interface Props {
  drawer?: Drawer | null;
  onToggleDrawer?: (d: Drawer) => void;
}

/** The drawer buttons are only shown on narrow screens (shell.css), where the side panels become drawers. */
export function TopBar({ drawer = null, onToggleDrawer }: Props) {
  const button = (d: Drawer, panelId: string, label: string) => (
    <button
      type="button"
      className="drawer-toggle"
      data-testid={`drawer-toggle-${d}`}
      aria-expanded={drawer === d}
      aria-controls={panelId}
      onClick={() => onToggleDrawer?.(d)}
    >
      {label}
    </button>
  );
  return (
    <header className="shell-topbar" data-testid="topbar">
      {button("layers", "layer-panel", es.drawers.layers)}
      <h1>{es.appTitle}</h1>
      <div className="topbar-actions">
        {button("inspector", "inspector-panel", es.drawers.inspector)}
        <ThemeToggle />
      </div>
    </header>
  );
}
