import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const KEY = "theme";
const listeners = new Set<() => void>();

function readStored(): Theme | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

function prefersDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

let current: Theme = readStored() ?? (prefersDark() ? "dark" : "light");
document.documentElement.dataset.theme = current;

export function getTheme(): Theme {
  return current;
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setTheme(theme: Theme): void {
  current = theme;
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* storage unavailable: the theme still applies for this session */
  }
  listeners.forEach((l) => l());
}

export function toggleTheme(): void {
  setTheme(current === "light" ? "dark" : "light");
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, getTheme);
}
