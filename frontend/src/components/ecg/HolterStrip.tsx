import { useEffect, useRef, useState } from "react";
import { useAppearance } from "@/app/appearance";
import type { Beat } from "@/data/types";
import { drawGrid, drawTrace, paperColors, setupCanvas } from "./paper";

export const BEAT_COLORS: Record<string, string> = { N: "#246BFD", S: "#D97706", V: "#7C3AED", F: "#DC2626" };

/** One strip of a long single-lead recording: 25 mm/s, 10 mm/mV, AI beat labels and RR intervals. */
export function HolterStrip({ signal, fs, start, seconds, beats, unusable = [], rows = 1, onBeatClick, offset = 0 }: {
  /** `offset`: the sample index of signal[0] in the recording (long recordings load only the part on screen) */
  signal: Float32Array; fs: number; start: number; seconds: number; beats: Beat[]; unusable?: [number, number][]; rows?: number; offset?: number;
  onBeatClick?: (b: Beat) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(900);
  const { appearance, resolvedTheme } = useAppearance();
  const colors = paperColors(appearance.ecgPaper, resolvedTheme === "dark");
  const perRow = seconds / rows;
  const pxPerSec = width / perRow;
  const pxPerMm = pxPerSec / 25;
  const rowH = Math.max(90, pxPerMm * 26);
  const height = rowH * rows;

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const ctx = setupCanvas(c, width, height);
    drawGrid(ctx, 0, 0, width, height, pxPerMm, colors);
    const pxPerMv = Math.min(pxPerMm * 10, rowH / 3.2);
    for (let r = 0; r < rows; r++) {
      const t0 = start + r * perRow, t1 = t0 + perRow;
      const y0 = r * rowH;
      for (const [a, b] of unusable) {
        if (b <= t0 || a >= t1) continue;
        ctx.fillStyle = "rgba(148,163,184,0.3)";
        ctx.fillRect((Math.max(a, t0) - t0) * pxPerSec, y0, (Math.min(b, t1) - Math.max(a, t0)) * pxPerSec, rowH);
      }
      const s0 = Math.max(0, Math.floor(t0 * fs) - offset), s1 = Math.min(signal.length, Math.ceil(t1 * fs) - offset);
      let base = 0;
      if (s1 > s0) {
        const seg = Array.from(signal.subarray(s0, s1)).sort((x, y) => x - y);
        base = seg[Math.floor(seg.length / 2)];
      }
      const shifted = new Float32Array(Math.max(0, s1 - s0));
      for (let i = 0; i < shifted.length; i++) shifted[i] = signal[s0 + i] - base;
      ctx.save();
      ctx.beginPath(); ctx.rect(0, y0, width, rowH); ctx.clip();
      drawTrace(ctx, shifted, 0, shifted.length, 0, pxPerSec / fs, y0 + rowH * 0.62, pxPerMv, colors.trace, 1.2);
      ctx.restore();
      ctx.font = "600 11px Inter Variable, Inter, sans-serif";
      const vis = beats.filter((b) => b.time_s >= t0 && b.time_s < t1);
      vis.forEach((b, i) => {
        const x = (b.time_s - t0) * pxPerSec;
        ctx.fillStyle = BEAT_COLORS[b.class];
        ctx.fillText(b.class, x - 3, y0 + 14);
        if (b.class !== "N") {
          ctx.globalAlpha = 0.12;
          ctx.fillRect(x - 0.12 * pxPerSec, y0 + 18, 0.24 * pxPerSec, rowH - 20);
          ctx.globalAlpha = 1;
        }
        if (i > 0) {
          const rr = Math.round((b.time_s - vis[i - 1].time_s) * 1000);
          ctx.fillStyle = colors.label;
          ctx.globalAlpha = rr > 2000 ? 1 : 0.65;
          ctx.font = rr > 2000 ? "700 10px Inter Variable, Inter, sans-serif" : "500 10px Inter Variable, Inter, sans-serif";
          const mx = ((b.time_s + vis[i - 1].time_s) / 2 - t0) * pxPerSec;
          ctx.fillText(String(rr), mx - 10, y0 + 28);
          ctx.globalAlpha = 1;
          ctx.font = "600 11px Inter Variable, Inter, sans-serif";
        }
      });
      ctx.fillStyle = colors.label;
      ctx.font = "500 10px Inter Variable, Inter, sans-serif";
      const mm = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
      ctx.fillText(mm(t0), 4, y0 + rowH - 5);
    }
  }, [signal, offset, fs, start, seconds, beats, unusable, rows, width, height, colors, pxPerMm, pxPerSec, rowH, perRow]);

  return (
    <div ref={wrap}>
      <canvas ref={canvas} className="block w-full rounded-xl" role="img" aria-label={`ECG strip from ${Math.round(start)} s`}
        onClick={(e) => {
          if (!onBeatClick) return;
          const rect = canvas.current!.getBoundingClientRect();
          const row = Math.floor((e.clientY - rect.top) / rowH);
          const t = start + row * perRow + (e.clientX - rect.left) / pxPerSec;
          const near = beats.reduce<Beat | null>((best, b) => (Math.abs(b.time_s - t) < 0.3 && (!best || Math.abs(b.time_s - t) < Math.abs(best.time_s - t)) ? b : best), null);
          if (near) onBeatClick(near);
        }} />
    </div>
  );
}
