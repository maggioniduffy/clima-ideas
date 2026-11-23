import { es, noEndDot } from "./es";

test("noEndDot strips trailing dots and spaces only", () => {
  expect(noEndDot("No es una alerta oficial.")).toBe("No es una alerta oficial");
  expect(noEndDot("a..  ")).toBe("a");
  expect(noEndDot("CC BY 4.0")).toBe("CC BY 4.0");
});

test("sentence builders never double the period", () => {
  expect(es.forecast.sourceLine("Fuente.", "2026/2027.", "CC0. No es una alerta oficial.")).toBe(
    "Fuente. Período 2026/2027. Licencia CC0. No es una alerta oficial.",
  );
  expect(es.forecast.sourceLine("A", "B", "C")).not.toMatch(/\.\./);
  expect(es.hindcast.licenseLine("L.", "O.")).toBe("Licencias: L. Observado: O.");
});
