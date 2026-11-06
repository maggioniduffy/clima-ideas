import { fireEvent, render, screen } from "@testing-library/react";
import { App } from "./App";
import { es } from "./i18n/es";

test("renders the app title from es.ts", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: es.appTitle })).toBeInTheDocument();
});

test("theme toggle flips data-theme without remounting", () => {
  render(<App />);
  const heading = screen.getByRole("heading", { name: es.appTitle });
  const before = document.documentElement.dataset.theme;
  fireEvent.click(screen.getByRole("button", { name: es.theme.toggle }));
  const after = document.documentElement.dataset.theme;
  expect(after).not.toBe(before);
  expect(["light", "dark"]).toContain(after);
  expect(screen.getByRole("heading", { name: es.appTitle })).toBe(heading);
  fireEvent.click(screen.getByRole("button", { name: es.theme.toggle }));
  expect(document.documentElement.dataset.theme).toBe(before);
});
