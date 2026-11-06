import { render, screen } from "@testing-library/react";
import { App } from "./App";
import { es } from "./i18n/es";

test("renders the app title from es.ts", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: es.appTitle })).toBeInTheDocument();
});
