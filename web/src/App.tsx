import { es } from "./i18n/es";
import "./theme/tokens.css";
import { toggleTheme, useTheme } from "./theme/themeStore";

export function App() {
  const theme = useTheme();
  return (
    <>
      <h1>{es.appTitle}</h1>
      <button
        type="button"
        aria-label={es.theme.toggle}
        onClick={toggleTheme}
        style={{
          width: 32,
          height: 32,
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border)",
          background: "var(--raised)",
          color: "var(--text)",
          cursor: "pointer",
        }}
      >
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.5" />
          {theme === "light" ? <path d="M8 2a6 6 0 0 0 0 12z" fill="currentColor" /> : <path d="M8 2a6 6 0 0 1 0 12z" fill="currentColor" />}
        </svg>
      </button>
    </>
  );
}
