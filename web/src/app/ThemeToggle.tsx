import { es } from "../i18n/es";
import { toggleTheme, useTheme } from "../theme/themeStore";

export function ThemeToggle() {
  const theme = useTheme();
  return (
    <button
      type="button"
      className="theme-toggle"
      data-testid="theme-toggle"
      aria-label={es.theme.toggle}
      onClick={toggleTheme}
    >
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.5" />
        {theme === "light" ? <path d="M8 2a6 6 0 0 0 0 12z" fill="currentColor" /> : <path d="M8 2a6 6 0 0 1 0 12z" fill="currentColor" />}
      </svg>
    </button>
  );
}
