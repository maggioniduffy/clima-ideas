import { render, screen } from "@testing-library/react";
import { es } from "../i18n/es";
import { Hero } from "./Hero";

test("only the h1 without numbers", () => {
  render(<Hero title="Capa A" source={{ source: "S", period: "2000" }} />);
  expect(screen.getByRole("heading", { level: 1, name: "Capa A" })).toBeInTheDocument();
  expect(screen.queryByTestId("hero-stats")).toBeNull();
  expect(screen.queryByTestId("hero-source")).toBeNull();
});

test("numbers with captions and one source and period line", () => {
  render(
    <Hero
      title="Ríos"
      stats={[{ id: "events-shown", value: 12, caption: es.hero.eventsShown }]}
      source={{ source: "ERA5", period: "1980/2025" }}
    />,
  );
  expect(screen.getByTestId("hero-stat-events-shown")).toHaveTextContent(`12${es.hero.eventsShown}`);
  expect(screen.getByTestId("hero-source")).toHaveTextContent("ERA5 · 1980/2025");
});
