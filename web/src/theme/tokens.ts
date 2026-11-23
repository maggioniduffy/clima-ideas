/** Mirrors tokens.css (docs/design.md); tokens.test.ts keeps them in sync. For deck.gl colors etc. */
export const tokens = {
  brand: { main: "#3E505B", secondary: "#A4AF69" },
  light: {
    bg: "#E4E2DC",
    "frame-0": "#F3F2EE",
    "frame-1": "#F1EEE4",
    "frame-2": "#F6E9B5",
    surface: "#FBFAF7",
    raised: "#EFECE4",
    border: "#D8D4C8",
    text: "#1C1C1C",
    "text-muted": "#4D4C48",
    ctrl: "#1C1C1C",
    "on-ctrl": "#F3F2EE",
    inverse: "#1C1C1C",
    "on-inverse": "#F3F2EE",
    accent: "#F5CF4B",
    water: "#3A6E8F",
    casing: "#1C1C1C",
    /** Glass panels over the map (rgba, so no contrast math: text sits on them via the backdrop) */
    "glass": "rgba(250,249,246,0.68)",
    "glass-line": "rgba(28,28,28,0.12)",
    "rule": "rgba(28,28,28,0.08)",
    "glass-hi": "rgba(255,255,255,0.6)",
    "glass-shadow": "rgba(40,36,28,0.10)",
    "well": "rgba(28,28,28,0.05)",
    "row-sel": "rgba(245,207,75,0.30)",
    "table-bg": "rgba(255,255,255,0.55)",
    /** Chart background: plain, no grain. The one pure white of the palette (docs/design.md). */
    "chart-surface": "#FFFFFF",
  },
  dark: {
    bg: "#101114",
    "frame-0": "#1B1C20",
    "frame-1": "#1D1D1F",
    "frame-2": "#2E2814",
    surface: "#26272C",
    raised: "#2A2B30",
    border: "#3C3D43",
    text: "#F1EFE8",
    "text-muted": "#BEBCB5",
    ctrl: "#F1EFE8",
    "on-ctrl": "#1B1C20",
    inverse: "#34353B",
    "on-inverse": "#F1EFE8",
    accent: "#F5CF4B",
    water: "#7FA9C6",
    casing: "#101114",
    "glass": "rgba(30,31,36,0.62)",
    "glass-line": "rgba(241,239,232,0.14)",
    "rule": "rgba(241,239,232,0.09)",
    "glass-hi": "rgba(255,255,255,0.06)",
    "glass-shadow": "rgba(0,0,0,0.35)",
    "well": "rgba(241,239,232,0.07)",
    "row-sel": "rgba(245,207,75,0.16)",
    "table-bg": "rgba(16,17,20,0.35)",
    /** Chart background: a solid flat well, darker than --surface and without grain. */
    "chart-surface": "#1B1C20",
  },
  /** IVT sequential ramp stops, low to high (evenly spaced over [0, IVT_SCALE_MAX]); `--ivt-0..5` in tokens.css. */
  ivtRamp: {
    light: ["#DCE6BE", "#8CCBB0", "#3FA3B8", "#2B6FB0", "#38399A", "#5A1A72"],
    dark: ["#22384A", "#2B5F80", "#1E9A9C", "#6BCB6C", "#E3E24A", "#F8F5B4"],
  },
  /** Sequential ramp of the AR count map (events per cell), low to high; `--count-0..4` in tokens.css. Not the IVT ramp. */
  countRamp: {
    light: ["#EFE8DA", "#D9C7A4", "#B79C70", "#8A6F46", "#55402A"],
    dark: ["#2A2F3C", "#4A4468", "#76588A", "#A77FA6", "#DDB9C6"],
  },
  /** Rain ramp (IMERG mm/h, convection layer), low to high; single-hue blue, neutral (no warning colors); `--rain-0..4` in tokens.css. */
  rainRamp: {
    light: ["#DCE8EC", "#A9C8D6", "#6FA0BD", "#3A6E96", "#1B3A5C"],
    dark: ["#24384A", "#2F5878", "#4A82A8", "#86B4D2", "#D6E8F2"],
  },
  /** Peak-discharge ramp of the debris-catchments layer, low to high; single-hue violet-grey, neutral (no warning colors); `--debris-0..4` in tokens.css. */
  debrisRamp: {
    light: ["#ECE8EE", "#C9BFD3", "#A394B8", "#7A69A0", "#4B3B78"],
    dark: ["#2B2836", "#443C63", "#6A5C98", "#9C8CC4", "#DCD3F0"],
  },
  /** Monochrome slate relief ramp (mockup), far/low to peaks (elevations in RELIEF_STOPS_M); `--relief-0..3` in tokens.css. */
  reliefRamp: {
    light: ["#A7AEAF", "#77848A", "#4A5A64", "#2A343B"],
    dark: ["#4E5F6A", "#7D8D96", "#B3BEC4", "#ECE7DC"],
  },
} as const;
