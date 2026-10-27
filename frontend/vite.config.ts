/// <reference types="vitest/config" />
import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Demo build: fully static (no backend). Demo data is served from /demo (public/demo).
export default defineConfig({
  plugins: [react()],
  base: process.env.VITE_BASE ?? "/",
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: { port: 5174 },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: { output: { manualChunks: { react: ["react", "react-dom", "react-router"], charts: ["recharts"] } } },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./tests/setup.ts"], include: ["tests/**/*.test.{ts,tsx}"], exclude: ["e2e/**", "node_modules/**"] },
});
