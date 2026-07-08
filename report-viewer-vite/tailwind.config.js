/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "Arial", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        "brand-bg": "#15161f",
        "brand-surface": "#1c1e2a",
        "brand-surface-raised": "#23263380",
        "brand-border": "#2c2f42",
        "brand-text": "#f4f5f9",
        "brand-muted": "#9297ac",
        "brand-red": "#e63946",
        "brand-red-dim": "#e6394626",
        "brand-amber": "#f2a93b",
        "brand-amber-dim": "#f2a93b26",
        "brand-yellow": "#e8c547",
        "brand-teal": "#0e8f88",
        "brand-teal-dim": "#0e8f8826",
      },
    },
  },
  plugins: [],
};
