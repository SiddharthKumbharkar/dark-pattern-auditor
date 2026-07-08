/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "Arial", "sans-serif"],
      },
      colors: {
        "brand-ink": "#14171f",
        "brand-paper": "#faf9f6",
        "brand-card": "#ffffff",
        "brand-muted": "#6b7280",
        "brand-border": "#e6e2da",
        "brand-accent": "#a9762f",
        "brand-accent-dark": "#8a5f22",
        "brand-danger": "#dc2626",
        "brand-danger-dark": "#b91c1c",
        "brand-success": "#16a34a",
      },
    },
  },
  plugins: [],
};
