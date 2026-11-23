import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { es } from "../i18n/es";
import { OFFICIAL_LINKS } from "./officialLinks";
import { ThemeToggle } from "./ThemeToggle";

interface Props {
  /** Short name of the selected active layer; the dark pill is left out when there is none. */
  activeName?: string | null;
  /** The layer list (opens in the dropdown). */
  children?: ReactNode;
}

/** Product name; a brand, not translated copy. */
const WORDMARK = "Clima Ideas";

/**
 * Floating menu (top-left, glass): menu button with the wordmark, the selected layer's pill and the theme button.
 * The button opens a dropdown with the layer list and the retrospective / official-warnings footer; it closes on
 * Escape and on a click outside. Closed by default.
 */
export function TopBar({ activeName = null, children }: Props) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    const onDown = (e: PointerEvent | MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);
  return (
    <header className="shell-topbar" ref={root}>
      <div className="topbar-bar glass" data-testid="topbar">
        <button
          ref={button}
          type="button"
          className="menu-toggle"
          data-testid="menu-toggle"
          aria-expanded={open}
          aria-controls={menuId}
          aria-label={open ? es.menu.close : es.menu.open}
          onClick={() => setOpen((o) => !o)}
        >
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M3 5h12M3 9h12M3 13h12" />
          </svg>
          <span className="topbar-brand" data-testid="topbar-brand">{WORDMARK}</span>
        </button>
        <span className="topbar-divider" aria-hidden="true" />
        {activeName && (
          <span className="topbar-active" data-testid="topbar-active" title={es.menu.activeLayer}>
            {activeName}
          </span>
        )}
        <ThemeToggle />
      </div>
      {open && (
        <div className="layer-menu glass" id={menuId} data-testid="layer-menu">
          {children}
          <p className="layer-menu-foot" data-testid="layer-menu-foot">
            {es.menu.retro} {es.hindcast.officialLead}{" "}
            {OFFICIAL_LINKS.map((l, i) => (
              <span key={l.id}>
                {i > 0 && es.events.sep}
                <a href={l.href} target="_blank" rel="noopener noreferrer" data-testid={`menu-link-${l.id}`}>
                  {es.hindcast.links[l.id]}
                </a>
              </span>
            ))}
            {es.hindcast.stop}
          </p>
        </div>
      )}
    </header>
  );
}
