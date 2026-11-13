/** Mirrors tokens.css (docs/design.md); tokens.test.ts keeps them in sync. For deck.gl colors etc. */
export const tokens = {
  brand: { main: "#3E505B", secondary: "#A4AF69" },
  light: {
    bg: "#F1EEE6",
    surface: "#F9F7F2",
    raised: "#EFECE4",
    border: "#DDD8CD",
    text: "#2A343B",
    "text-muted": "#5F6468",
    ctrl: "#3E505B",
    "on-ctrl": "#F5F2EA",
    accent: "#8EB8E5",
    water: "#3A6E8F",
    casing: "#2A343B",
  },
  dark: {
    bg: "#16212A",
    surface: "#1F2D37",
    raised: "#2A3A46",
    border: "#3E505B",
    text: "#ECE7DC",
    "text-muted": "#A3AEB4",
    ctrl: "#4D6372",
    "on-ctrl": "#ECE7DC",
    accent: "#FDDA0D",
    water: "#7FA9C6",
    casing: "#16212A",
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
  /** Monochrome slate relief ramp (mockup), far/low to peaks (elevations in RELIEF_STOPS_M); `--relief-0..3` in tokens.css. */
  reliefRamp: {
    light: ["#A7AEAF", "#77848A", "#4A5A64", "#2A343B"],
    dark: ["#4E5F6A", "#7D8D96", "#B3BEC4", "#ECE7DC"],
  },
} as const;
