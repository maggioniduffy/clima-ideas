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
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
        <circle cx="9" cy="9" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
        {theme === "light" ? <path d="M9 2.5 A6.5 6.5 0 0 0 9 15.5 Z" fill="currentColor" /> : <path d="M9 2.5 A6.5 6.5 0 0 1 9 15.5 Z" fill="currentColor" />}
      </svg>
    </button>
  );
}
