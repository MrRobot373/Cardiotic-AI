/// <reference types="vitest/config" />
import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// One build, two ways to run: against the Cardiotic server (detected at start-up) or static with the sample data in public/data.
export default defineConfig({
  plugins: [react()],
  base: process.env.VITE_BASE ?? "/",
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  // CARDIOTIC_API: run the app against a local Cardiotic server (npm run dev:server)
  server: { port: 5174, proxy: process.env.CARDIOTIC_API ? { "/api": { target: process.env.CARDIOTIC_API, changeOrigin: false } } : undefined },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: { output: { manualChunks: { react: ["react", "react-dom", "react-router"], charts: ["recharts"] } } },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./tests/setup.ts"], include: ["tests/**/*.test.{ts,tsx}"], exclude: ["e2e/**", "node_modules/**"] },
});
