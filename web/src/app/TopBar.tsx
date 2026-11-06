import { es } from "../i18n/es";
import { ThemeToggle } from "./ThemeToggle";

export function TopBar() {
  return (
    <header className="shell-topbar" data-testid="topbar">
      <h1>{es.appTitle}</h1>
      <ThemeToggle />
    </header>
  );
}
