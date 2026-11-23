import type { ReactNode } from "react";
import { ThemeToggle } from "./ThemeToggle";

interface Props {
  /** The layer pills. */
  children?: ReactNode;
}

/** Product name; a brand, not translated copy. */
const WORDMARK = "Clima Ideas";

/** Header: logo pill, layer pills (one scrolling row on narrow screens) and the round theme button. */
export function TopBar({ children }: Props) {
  return (
    <header className="shell-topbar" data-testid="topbar">
      <span className="topbar-brand" data-testid="topbar-brand">{WORDMARK}</span>
      {children}
      <div className="topbar-actions">
        <ThemeToggle />
      </div>
    </header>
  );
}
