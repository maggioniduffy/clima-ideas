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

test.each(["light", "dark"] as const)("%s relief ramp matches tokens.css", (theme) => {
  const b = block(`:root[data-theme="${theme}"]`);
  expect(tokens.reliefRamp[theme]).toHaveLength(4);
  tokens.reliefRamp[theme].forEach((v, i) => expect(b[`--relief-${i}`]).toBe(v));
});

test("no pure white or black anywhere", () => {
  expect(css).not.toMatch(/#(fff|ffffff|000|000000)\b/i);
  const all = [...Object.values(tokens.brand), ...Object.values(tokens.light), ...Object.values(tokens.dark),
    ...tokens.ivtRamp.light, ...tokens.ivtRamp.dark, ...tokens.reliefRamp.light, ...tokens.reliefRamp.dark];
  for (const v of all) expect(v.toLowerCase()).not.toMatch(/^#(fff|ffffff|000|000000)$/);
});
