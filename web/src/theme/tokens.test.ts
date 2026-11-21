import { expect, test } from "vitest";
import { readFileSync } from "node:fs";
import { tokens } from "./tokens";

const css = readFileSync("src/theme/tokens.css", "utf8");

function block(selector: string): Record<string, string> {
  const re = new RegExp(`${selector.replace(/[[\]"]/g, "\\$&")}\\s*{([^}]*)}`);
  const body = css.match(re)?.[1] ?? "";
  return Object.fromEntries(
    [...body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]),
  );
}

test("brand tokens match tokens.css", () => {
  const root = block(":root");
  for (const [k, v] of Object.entries(tokens.brand)) expect(root[`--${k}`]).toBe(v);
  expect(root["--accent"]).toBeUndefined(); // the accent is per theme
});

test("per-theme accent", () => {
  expect(tokens.light.accent).toBe("#8EB8E5");
  expect(tokens.dark.accent).toBe("#FDDA0D");
});

test("mockup neutrals and control tokens", () => {
  expect(tokens.light).toMatchObject({ bg: "#F1EEE6", surface: "#F9F7F2", raised: "#EFECE4", border: "#DDD8CD", "text-muted": "#5F6468", ctrl: "#3E505B", "on-ctrl": "#F5F2EA", water: "#3A6E8F", casing: "#2A343B" });
  expect(tokens.dark).toMatchObject({ ctrl: "#4D6372", "on-ctrl": "#ECE7DC", water: "#7FA9C6", casing: "#16212A" });
});

test.each(["light", "dark"] as const)("%s texture variables", (theme) => {
  const b = block(`:root[data-theme="${theme}"]`);
  expect(b["--tex"]).toBe(theme === "light" ? "radial-gradient(rgba(42, 52, 59, 0.09) 0.9px, transparent 1.3px)" : "none");
  expect(b["--shine"]).toBe(theme === "light" ? "rgba(255, 255, 255, 0.45)" : "transparent");
});

test.each(["light", "dark"] as const)("%s neutrals match tokens.css", (theme) => {
  const b = block(`:root[data-theme="${theme}"]`);
  for (const [k, v] of Object.entries(tokens[theme])) expect(b[`--${k}`]).toBe(v);
});

test.each(["light", "dark"] as const)("%s IVT ramp matches tokens.css", (theme) => {
  const b = block(`:root[data-theme="${theme}"]`);
  expect(tokens.ivtRamp[theme]).toHaveLength(6);
  tokens.ivtRamp[theme].forEach((v, i) => expect(b[`--ivt-${i}`]).toBe(v));
});

test.each(["light", "dark"] as const)("%s rain ramp matches tokens.css", (theme) => {
  const b = block(`:root[data-theme="${theme}"]`);
  expect(tokens.rainRamp[theme]).toHaveLength(5);
  tokens.rainRamp[theme].forEach((v, i) => expect(b[`--rain-${i}`]).toBe(v));
});

test.each(["light", "dark"] as const)("%s debris ramp matches tokens.css", (theme) => {
  const b = block(`:root[data-theme="${theme}"]`);
  expect(tokens.debrisRamp[theme]).toHaveLength(5);
  tokens.debrisRamp[theme].forEach((v, i) => expect(b[`--debris-${i}`]).toBe(v));
});

test.each(["light", "dark"] as const)("%s relief ramp matches tokens.css", (theme) => {
  const b = block(`:root[data-theme="${theme}"]`);
  expect(tokens.reliefRamp[theme]).toHaveLength(4);
  tokens.reliefRamp[theme].forEach((v, i) => expect(b[`--relief-${i}`]).toBe(v));
});

const lum = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
};

test("chart surface: pure white in light, a flat dark well in dark (no grain)", () => {
  expect(tokens.light["chart-surface"]).toBe("#FFFFFF");
  expect(tokens.dark["chart-surface"]).not.toBe(tokens.dark.surface);
  expect(tokens.dark["chart-surface"]).toMatch(/^#[0-9A-F]{6}$/);
  expect(block(':root[data-theme="light"]')["--chart-surface"]).toBe("#FFFFFF");
});

test.each(["light", "dark"] as const)("%s chart ink keeps its contrast on the chart surface", (theme) => {
  const t = tokens[theme];
  const bg = t["chart-surface"];
  expect(contrast(t.text, bg)).toBeGreaterThanOrEqual(7); // axes, curves
  expect(contrast(t["text-muted"], bg)).toBeGreaterThanOrEqual(4.5); // tick labels, Gumbel baseline, bands
  expect(contrast(t.water, bg)).toBeGreaterThanOrEqual(4.5); // sensitivity scenarios
  // accent and secondary dots are drawn with a casing outline: the accent itself needs 3:1 only in dark, where it is the fill
  if (theme === "light") expect(contrast(t.casing, bg)).toBeGreaterThanOrEqual(7);
  else expect(contrast(t.accent, bg)).toBeGreaterThanOrEqual(3);
});

test("no pure white or black anywhere, except the light chart surface", () => {
  expect(css.replace("--chart-surface: #FFFFFF;", "")).not.toMatch(/#(fff|ffffff|000|000000)\b/i);
  const strip = <T extends Record<string, string>>(o: T) => Object.entries(o).filter(([k]) => k !== "chart-surface").map(([, v]) => v);
  const all = [...Object.values(tokens.brand), ...strip(tokens.light), ...strip(tokens.dark),
    ...tokens.ivtRamp.light, ...tokens.ivtRamp.dark, ...tokens.reliefRamp.light, ...tokens.reliefRamp.dark];
  for (const v of all) expect(v.toLowerCase()).not.toMatch(/^#(fff|ffffff|000|000000)$/);
});
