import { beforeEach, expect, test, vi } from "vitest";

function mockPrefersDark(dark: boolean) {
  window.matchMedia = vi.fn().mockImplementation((q: string) => ({
    matches: dark && q.includes("dark"),
    media: q,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

async function freshStore() {
  vi.resetModules();
  return import("./themeStore");
}

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  mockPrefersDark(false);
});

test("falls back to prefers-color-scheme: dark", async () => {
  mockPrefersDark(true);
  const s = await freshStore();
  expect(s.getTheme()).toBe("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
});

test("falls back to light when no preference", async () => {
  const s = await freshStore();
  expect(s.getTheme()).toBe("light");
});

test("reads the stored value over prefers-color-scheme", async () => {
  mockPrefersDark(true);
  localStorage.setItem("theme", "light");
  const s = await freshStore();
  expect(s.getTheme()).toBe("light");
  expect(document.documentElement.dataset.theme).toBe("light");
});

test("toggleTheme flips dataset.theme, persists and notifies", async () => {
  const s = await freshStore();
  const listener = vi.fn();
  s.subscribe(listener);
  s.toggleTheme();
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("theme")).toBe("dark");
  expect(listener).toHaveBeenCalledTimes(1);
  s.toggleTheme();
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(localStorage.getItem("theme")).toBe("light");
});

test("setTheme works when localStorage throws", async () => {
  const s = await freshStore();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("denied");
  });
  s.setTheme("dark");
  expect(s.getTheme()).toBe("dark");
  vi.restoreAllMocks();
});
