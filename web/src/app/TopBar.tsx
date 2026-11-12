import { es } from "../i18n/es";
import { ThemeToggle } from "./ThemeToggle";

/** Only the layers panel is a drawer (narrow screens); the card row stacks under the map instead. */
export type Drawer = "layers";

interface Props {
  drawer?: Drawer | null;
  onToggleDrawer?: (d: Drawer) => void;
}

/** Product name; a brand, not translated copy. */
const WORDMARK = "Clima Ideas";

/** The logo mark of the design (colors from the theme tokens, so it follows light/dark). */
function LogoMark() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true" focusable="false">
      <rect width="28" height="28" rx="6" style={{ fill: "var(--ctrl)" }} />
      <path
        d="M6 17 L11 9 L15 15 L18 11 L22 17"
        fill="none"
        style={{ stroke: "var(--on-ctrl)" }}
        strokeWidth="1.8"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <path d="M6 21 H22" style={{ stroke: "var(--accent)" }} strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/** The drawer button is only shown on narrow screens (shell.css), where the layers panel becomes a drawer. */
export function TopBar({ drawer = null, onToggleDrawer }: Props) {
  return (
    <header className="shell-topbar tx" data-testid="topbar">
      <button
        type="button"
        className="drawer-toggle"
        data-testid="drawer-toggle-layers"
        aria-expanded={drawer === "layers"}
        aria-controls="layer-panel"
        onClick={() => onToggleDrawer?.("layers")}
      >
        {es.drawers.layers}
      </button>
      <div className="topbar-brand">
        <LogoMark />
        <span className="topbar-wordmark">{WORDMARK}</span>
      </div>
      <h1>{es.appTitle}</h1>
      <div className="topbar-actions">
        <ThemeToggle />
      </div>
    </header>
  );
}
