import { useEffect, useMemo, useRef, useState } from "react";
import { useAppearance } from "@/app/appearance";
import { drawCalibration, drawGrid, drawTrace, leadLabel, paperColors, setupCanvas } from "./paper";

export type Layout = "3x4" | "6x2" | "12x1";
const LEADS = ["I", "II", "III", "AVR", "AVL", "AVF", "V1", "V2", "V3", "V4", "V5", "V6"];

interface Panel { lead: string; col: number; row: number; t0: number; t1: number; }

function panels(layout: Layout, dur: number): { panels: Panel[]; rows: number; cols: number; rhythm: boolean } {
  if (layout === "12x1") return { panels: LEADS.map((l, i) => ({ lead: l, col: 0, row: i, t0: 0, t1: dur })), rows: 12, cols: 1, rhythm: false };
  if (layout === "6x2") {
    const half = dur / 2;
    return { panels: LEADS.map((l, i) => ({ lead: l, col: i < 6 ? 0 : 1, row: i % 6, t0: i < 6 ? 0 : half, t1: i < 6 ? half : dur })), rows: 6, cols: 2, rhythm: true };
  }
  const q = dur / 4;
  const grid = [["I", "AVR", "V1", "V4"], ["II", "AVL", "V2", "V5"], ["III", "AVF", "V3", "V6"]];
  return { panels: grid.flatMap((row, r) => row.map((l, c) => ({ lead: l, col: c, row: r, t0: c * q, t1: (c + 1) * q }))), rows: 3, cols: 4, rhythm: true };
}

export interface Ecg12ViewProps {
  leads: Record<string, Float32Array>;
  fs: number;
  layout?: Layout;
  speed?: 25 | 50;
  gain?: 5 | 10 | 20;
  rhythmLead?: string;
  beats?: { t: number; label?: string; tone?: "normal" | "ectopic" }[];
  leadQuality?: Record<string, "good" | "noisy" | "unusable">;
  highlightLeads?: string[];
  caliper?: boolean;
  header?: { left: string; right: string };
  className?: string;
  /** Print and report views: always light ECG paper. */
  forceLight?: boolean;
}

export function Ecg12View({ leads, fs, layout = "3x4", speed = 25, gain = 10, rhythmLead = "II", beats = [], leadQuality = {}, highlightLeads = [], caliper = false, header, className, forceLight = false }: Ecg12ViewProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(1000);
  const [cal, setCal] = useState<{ x0: number; x1: number; y: number } | null>(null);
  const { appearance, resolvedTheme } = useAppearance();
  const dark = resolvedTheme === "dark" && !forceLight;
  const colors = paperColors(appearance.ecgPaper, dark);
  const dur = (leads.II?.length ?? 0) / fs;
  const geo = useMemo(() => panels(layout, dur), [layout, dur]);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const calMm = 7;
  const headerMm = header ? 7 : 2;
  const rowMm = layout === "12x1" ? Math.max(11, gain * 1.4) : Math.max(18, gain * 2.4);
  // never below ~3 px/mm: on phones the ECG keeps a readable scale and scrolls sideways
  const pxPerMm = Math.max(3, width / (calMm + 10 * 25));
  const widthPx = (calMm + dur * speed) * pxPerMm;
  const rowsTotal = geo.rows + (geo.rhythm ? 1 : 0);
  const heightPx = (headerMm + rowsTotal * rowMm + 3) * pxPerMm;
  const pxPerSec = speed * pxPerMm;
  const pxPerMv = gain * pxPerMm;

  useEffect(() => {
    const c = canvas.current;
    if (!c || !leads.II) return;
    const ctx = setupCanvas(c, widthPx, heightPx);
    drawGrid(ctx, 0, 0, widthPx, heightPx, pxPerMm, colors);
    ctx.font = `600 ${Math.max(10, pxPerMm * 2.6)}px Inter Variable, Inter, sans-serif`;
    if (header) {
      ctx.fillStyle = colors.label;
      ctx.fillText(header.left, calMm * pxPerMm, pxPerMm * 4.6);
      const w = ctx.measureText(header.right).width;
      ctx.fillText(header.right, widthPx - w - pxPerMm * 2, pxPerMm * 4.6);
    }
    const x0 = calMm * pxPerMm;
    const rowY = (r: number) => (headerMm + (r + 0.62) * rowMm) * pxPerMm;
    const colW = (dur / geo.cols) * pxPerSec;
    for (let r = 0; r < rowsTotal; r++) drawCalibration(ctx, pxPerMm, rowY(r), pxPerMm, pxPerMv, colors.trace);
    for (const p of geo.panels) {
      const px = x0 + p.col * colW;
      const y = rowY(p.row);
      const q = leadQuality[p.lead];
      if (highlightLeads.includes(p.lead)) {
        ctx.fillStyle = dark ? "rgba(110,168,255,0.12)" : "rgba(36,107,253,0.07)";
        ctx.fillRect(px + 1, (headerMm + p.row * rowMm) * pxPerMm + 2, colW - 2, rowMm * pxPerMm - 4);
        ctx.strokeStyle = colors.accent;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(px + 1, (headerMm + p.row * rowMm) * pxPerMm + 2, colW - 2, rowMm * pxPerMm - 4);
      }
      if (q && q !== "good") {
        ctx.save();
        ctx.fillStyle = q === "unusable" ? "rgba(148,163,184,0.30)" : "rgba(245,158,11,0.06)";
        ctx.fillRect(px, (headerMm + p.row * rowMm) * pxPerMm, colW, rowMm * pxPerMm);
        if (q === "noisy") {
          ctx.fillStyle = "rgba(217,119,6,0.9)";
          ctx.fillRect(px, (headerMm + p.row * rowMm) * pxPerMm + 1, colW, 2);
        }
        ctx.restore();
      }
      const data = leads[p.lead];
      if (data) {
        const base = median(data, Math.floor(p.t0 * fs), Math.floor(p.t1 * fs));
        ctx.save();
        ctx.beginPath();
        ctx.rect(px, (headerMm + p.row * rowMm) * pxPerMm - rowMm * pxPerMm * 0.4, colW, rowMm * pxPerMm * 1.6);
        ctx.clip();
        drawTrace(ctx, shift(data, base), p.t0 * fs, p.t1 * fs, px, pxPerSec / fs, y, pxPerMv, colors.trace);
        ctx.restore();
      }
      ctx.fillStyle = colors.label;
      ctx.fillText(leadLabel(p.lead) + (q && q !== "good" ? `  (${q})` : ""), px + pxPerMm * 1.2, y - rowMm * pxPerMm * 0.34);
      if (p.col > 0) {
        ctx.strokeStyle = colors.trace;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(px, y - pxPerMm * 2.5);
        ctx.lineTo(px, y + pxPerMm * 2.5);
        ctx.stroke();
      }
    }
    if (geo.rhythm && leads[rhythmLead]) {
      const r = geo.rows;
      const y = rowY(r);
      const d = leads[rhythmLead];
      drawTrace(ctx, shift(d, median(d, 0, d.length)), 0, d.length, x0, pxPerSec / fs, y, pxPerMv, colors.trace);
      ctx.fillStyle = colors.label;
      ctx.fillText(`${leadLabel(rhythmLead)} (rhythm)`, x0 + pxPerMm * 1.2, y + rowMm * pxPerMm * 0.3);
      ctx.font = `600 ${Math.max(9, pxPerMm * 2.2)}px Inter Variable, Inter, sans-serif`;
      beats.forEach((b, i) => {
        const bx = x0 + b.t * pxPerSec;
        ctx.fillStyle = b.tone === "ectopic" ? "#7C3AED" : colors.accent;
        const lbl = b.label ?? "•";
        ctx.fillText(lbl, bx - ctx.measureText(lbl).width / 2, y - rowMm * pxPerMm * 0.36);
        if (i > 0) {
          const rr = Math.round((b.t - beats[i - 1].t) * 1000);
          const mx = x0 + ((b.t + beats[i - 1].t) / 2) * pxPerSec;
          ctx.fillStyle = colors.label;
          ctx.globalAlpha = 0.75;
          const s = String(rr);
          ctx.fillText(s, mx - ctx.measureText(s).width / 2, y - rowMm * pxPerMm * 0.2);
          ctx.globalAlpha = 1;
        }
      });
    }
    if (cal) {
      const a = Math.min(cal.x0, cal.x1), b = Math.max(cal.x0, cal.x1);
      ctx.strokeStyle = colors.accent;
      ctx.fillStyle = colors.accent;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([5, 4]);
      for (const x of [a, b]) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, heightPx); ctx.stroke(); }
      ctx.setLineDash([]);
      ctx.beginPath(); ctx.moveTo(a, cal.y); ctx.lineTo(b, cal.y); ctx.stroke();
      const ms = ((b - a) / pxPerSec) * 1000;
      const txt = `${Math.round(ms)} ms${ms > 150 ? ` · ${Math.round(60000 / ms)} bpm` : ""}`;
      ctx.font = `600 ${Math.max(11, pxPerMm * 2.8)}px Inter Variable, Inter, sans-serif`;
      const tw = ctx.measureText(txt).width;
      ctx.fillStyle = colors.accent;
      ctx.fillRect((a + b) / 2 - tw / 2 - 6, cal.y - 24, tw + 12, 20);
      ctx.fillStyle = "#fff";
      ctx.fillText(txt, (a + b) / 2 - tw / 2, cal.y - 9);
    }
  }, [leads, fs, geo, widthPx, heightPx, pxPerMm, pxPerSec, pxPerMv, colors, header, leadQuality, highlightLeads, beats, rhythmLead, cal, dark, rowMm, headerMm, rowsTotal, dur]);

  const pos = (e: React.PointerEvent) => {
    const r = canvas.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const dragging = useRef(false);
  return (
    <div ref={wrap} className={className}>
      <div className="overflow-x-auto rounded-xl border border-black/5 dark:border-white/5">
        <canvas
          ref={canvas}
          role="img"
          aria-label={`12-lead ECG, ${layout} layout, ${speed} mm/s, ${gain} mm/mV`}
          className={caliper ? "cursor-crosshair touch-none" : undefined}
          onPointerDown={(e) => { if (!caliper) return; const p = pos(e); dragging.current = true; setCal({ x0: p.x, x1: p.x, y: p.y }); (e.target as Element).setPointerCapture(e.pointerId); }}
          onPointerMove={(e) => { if (!caliper || !dragging.current) return; const p = pos(e); setCal((c) => (c ? { ...c, x1: p.x } : c)); }}
          onPointerUp={() => { dragging.current = false; }}
          onDoubleClick={() => setCal(null)}
        />
      </div>
    </div>
  );
}

function median(d: Float32Array, a: number, b: number) {
  const s = Array.from(d.subarray(Math.max(0, a), Math.min(d.length, b)));
  if (!s.length) return 0;
  s.sort((x, y) => x - y);
  return s[Math.floor(s.length / 2)];
}

function shift(d: Float32Array, by: number) {
  if (!by) return d;
  const o = new Float32Array(d.length);
  for (let i = 0; i < d.length; i++) o[i] = d[i] - by;
  return o;
}
