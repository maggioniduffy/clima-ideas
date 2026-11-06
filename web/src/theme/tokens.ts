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
} as const;
