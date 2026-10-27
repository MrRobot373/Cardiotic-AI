import type { Config } from "tailwindcss";

// Every color is a CSS variable (HSL triplet) so themes, accent colors and contrast
// modes are switched at runtime without rebuilding. See src/styles/index.css.
const v = (name: string) => `hsl(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: v("background"),
        foreground: v("foreground"),
        card: { DEFAULT: v("card"), foreground: v("card-foreground") },
        popover: { DEFAULT: v("popover"), foreground: v("foreground") },
        muted: { DEFAULT: v("muted"), foreground: v("muted-foreground") },
        subtle: v("subtle"),
        border: v("border"),
        input: v("input"),
        ring: v("ring"),
        primary: { DEFAULT: v("primary"), foreground: v("primary-foreground"), soft: v("primary-soft"), "soft-foreground": v("primary-soft-foreground") },
        success: { DEFAULT: v("success"), soft: v("success-soft"), foreground: v("success-foreground") },
        warning: { DEFAULT: v("warning"), soft: v("warning-soft"), foreground: v("warning-foreground") },
        danger: { DEFAULT: v("danger"), soft: v("danger-soft"), foreground: v("danger-foreground") },
        info: { DEFAULT: v("info"), soft: v("info-soft"), foreground: v("info-foreground") },
        strong: { DEFAULT: v("strong"), foreground: v("strong-foreground") },
        sidebar: { DEFAULT: v("sidebar"), foreground: v("sidebar-foreground"), border: v("sidebar-border"), active: v("sidebar-active") },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        xl: "calc(var(--radius) + 4px)",
        "2xl": "calc(var(--radius) + 8px)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgb(var(--shadow) / 0.05)",
        card: "0 1px 2px 0 rgb(var(--shadow) / 0.04), 0 8px 24px -12px rgb(var(--shadow) / 0.12)",
        float: "0 18px 50px -20px rgb(var(--shadow) / 0.35), 0 2px 6px rgb(var(--shadow) / 0.06)",
        pop: "0 10px 38px -10px rgb(var(--shadow) / 0.25), 0 10px 20px -15px rgb(var(--shadow) / 0.2)",
        ring: "0 0 0 3px hsl(var(--ring) / 0.25)",
      },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-up": { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        "scale-in": { from: { opacity: "0", transform: "scale(0.97)" }, to: { opacity: "1", transform: "scale(1)" } },
        "slide-in-right": { from: { transform: "translateX(100%)" }, to: { transform: "translateX(0)" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
        blink: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0" } },
      },
      animation: {
        "fade-in": "fade-in 150ms ease-out",
        "slide-up": "slide-up 200ms cubic-bezier(0.16,1,0.3,1)",
        "scale-in": "scale-in 150ms cubic-bezier(0.16,1,0.3,1)",
        "slide-in-right": "slide-in-right 250ms cubic-bezier(0.16,1,0.3,1)",
        blink: "blink 1s step-end infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
