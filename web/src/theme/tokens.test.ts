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
  expect(root["--accent"]).toBeUndefined(); // the accent lives in the theme blocks (same value in both)
});

test("accent is the same in both themes", () => {
  expect(tokens.light.accent).toBe("#F5CF4B");
  expect(tokens.dark.accent).toBe("#F5CF4B");
});

test("Arena neutrals, frame gradient and control tokens", () => {
  expect(tokens.light).toMatchObject({
    bg: "#E4E2DC", "frame-0": "#F3F2EE", "frame-1": "#F1EEE4", "frame-2": "#F6E9B5", surface: "#FBFAF7", raised: "#EFECE4",
    border: "#D8D4C8", text: "#1C1C1C", "text-muted": "#5E5E5E", ctrl: "#1C1C1C", "on-ctrl": "#F3F2EE",
    inverse: "#1C1C1C", "on-inverse": "#F3F2EE", casing: "#1C1C1C", water: "#3A6E8F",
  });
  expect(tokens.dark).toMatchObject({
    bg: "#101114", "frame-0": "#1B1C20", "frame-1": "#1D1D1F", "frame-2": "#2E2814", surface: "#26272C", raised: "#2A2B30",
    border: "#3C3D43", text: "#F1EFE8", "text-muted": "#A9A9A4", ctrl: "#F1EFE8", "on-ctrl": "#1B1C20",
    inverse: "#34353B", "on-inverse": "#F1EFE8", casing: "#101114", water: "#7FA9C6", "chart-surface": "#1B1C20",
  });
});

test("card texture is gone", () => {
  expect(css).not.toMatch(/--tex\b|--shine|\.tx\b/);
});

test("Outfit is the UI font, IBM Plex Mono stays for numbers", () => {
  const root = block(":root");
  expect(root["--font-sans"]).toMatch(/^"Outfit"/);
  expect(root["--font-mono"]).toMatch(/^"IBM Plex Mono"/);
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

test.each(["light", "dark"] as const)("%s text pairs meet WCAG AA", (theme) => {
  const t = tokens[theme];
  for (const bg of [t.surface, t.raised, t["frame-0"], t["frame-1"], t["frame-2"], t.bg]) {
    expect(contrast(t.text, bg)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(t["text-muted"], bg)).toBeGreaterThanOrEqual(4.5);
  }
  expect(contrast(t["on-ctrl"], t.ctrl)).toBeGreaterThanOrEqual(4.5);
  expect(contrast(t["on-inverse"], t.inverse)).toBeGreaterThanOrEqual(4.5);
  expect(contrast(t.casing, t.accent)).toBeGreaterThanOrEqual(4.5); // dark text on the accent
  // accent glyph on the play button: only light has it (dark --ctrl is light, so the glyph needs the casing instead; see docs/design.md)
  if (theme === "light") expect(contrast(t.accent, t.ctrl)).toBeGreaterThanOrEqual(3);
  expect(contrast(t.accent, t.inverse)).toBeGreaterThanOrEqual(3);
});

test("no pure white or black anywhere, except the light chart surface", () => {
  expect(css.replace("--chart-surface: #FFFFFF;", "")).not.toMatch(/#(fff|ffffff|000|000000)\b/i);
  const strip = <T extends Record<string, string>>(o: T) => Object.entries(o).filter(([k]) => k !== "chart-surface").map(([, v]) => v);
  const all = [...Object.values(tokens.brand), ...strip(tokens.light), ...strip(tokens.dark),
    ...tokens.ivtRamp.light, ...tokens.ivtRamp.dark, ...tokens.reliefRamp.light, ...tokens.reliefRamp.dark];
  for (const v of all) expect(v.toLowerCase()).not.toMatch(/^#(fff|ffffff|000|000000)$/);
});
