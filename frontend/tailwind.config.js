/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 현대홈쇼핑 브랜드 틸 — 단일 액센트(파랑/인디고 대체)
        brand: {
          50: "#e8f6f3",
          100: "#c6e9e1",
          200: "#9bd9cb",
          600: "#1aa088",
          700: "#15806d",
        },
      },
    },
  },
  plugins: [],
};
