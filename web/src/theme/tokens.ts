/** Mirrors tokens.css (docs/design.md); tokens.test.ts keeps them in sync. For deck.gl colors etc. */
export const tokens = {
  brand: { main: "#3E505B", accent: "#8EB8E5", secondary: "#A4AF69" },
  light: {
    bg: "#F5F2EA",
    surface: "#ECE8DE",
    raised: "#E2DDD1",
    border: "#D3CDBF",
    text: "#2A343B",
    "text-muted": "#6E7377",
  },
  dark: {
    bg: "#16212A",
    surface: "#1F2D37",
    raised: "#2A3A46",
    border: "#3E505B",
    text: "#ECE7DC",
    "text-muted": "#A3AEB4",
  },
  /** IVT sequential ramp stops, low to high (evenly spaced over [0, IVT_SCALE_MAX]); `--ivt-0..5` in tokens.css. */
  ivtRamp: {
    light: ["#DCE6BE", "#8CCBB0", "#3FA3B8", "#2B6FB0", "#38399A", "#5A1A72"],
    dark: ["#22384A", "#2B5F80", "#1E9A9C", "#6BCB6C", "#E3E24A", "#F8F5B4"],
  },
  /** Monochrome slate relief ramp (mockup), far/low to peaks (elevations in RELIEF_STOPS_M); `--relief-0..3` in tokens.css. */
  reliefRamp: {
    light: ["#C4CBCC", "#8B989E", "#4A5A64", "#1C262D"],
    dark: ["#3A4852", "#76878F", "#BAC5CB", "#F6F1E6"],
  },
} as const;
