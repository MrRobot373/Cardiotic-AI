import { useEffect, useRef, useState } from "react";
import { useAppearance } from "@/app/appearance";
import { cn } from "@/lib/utils";
import { drawGrid, drawTrace, leadLabel, paperColors, setupCanvas } from "./paper";

/** Fiducials in ms relative to the R peak of the median beat. */
export interface Calipers {
  pOn: number | null;
  qrsOn: number;
  qrsOff: number;
  tEnd: number | null;
}
type Key = keyof Calipers;

const LINES: { key: Key; label: string; color: string }[] = [
  { key: "pOn", label: "P", color: "#246BFD" },
  { key: "qrsOn", label: "Q", color: "#059669" },
  { key: "qrsOff", label: "J", color: "#059669" },
  { key: "tEnd", label: "T", color: "#DC2626" },
];
const ORDER = ["I", "AVR", "V1", "V4", "II", "AVL", "V2", "V5", "III", "AVF", "V3", "V6"];

function Panel({ lead, data, fs, r, cal, edit, onDrag, quality }: {
  lead: string; data: Float32Array; fs: number; r: number; cal: Calipers; edit: boolean; quality?: string;
  onDrag: (k: Key, ms: number) => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(220);
  const drag = useRef<Key | null>(null);
  const { appearance, resolvedTheme } = useAppearance();
  const colors = paperColors(appearance.ecgPaper, resolvedTheme === "dark");
  const h = Math.round(w * 0.62);
  const msTotal = (data.length / fs) * 1000;
  const xOf = (ms: number) => ((ms + (r / fs) * 1000) / msTotal) * w;
  const msOf = (x: number) => (x / w) * msTotal - (r / fs) * 1000;

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const ctx = setupCanvas(c, w, h);
    const pxPerMs = w / msTotal;
    const pxPerMm = pxPerMs * 40; // 25 mm/s → 1 mm = 40 ms
    drawGrid(ctx, 0, 0, w, h, pxPerMm, colors);
    // QRS shading
    ctx.fillStyle = resolvedTheme === "dark" ? "rgba(16,185,129,0.12)" : "rgba(5,150,105,0.08)";
    ctx.fillRect(xOf(cal.qrsOn), 0, xOf(cal.qrsOff) - xOf(cal.qrsOn), h);
    let base = 0;
    const qi = Math.round(r + (cal.qrsOn / 1000) * fs);
    if (qi > 2 && qi < data.length) base = (data[qi - 1] + data[qi - 2]) / 2;
    const shifted = new Float32Array(data.length);
    for (let i = 0; i < data.length; i++) shifted[i] = data[i] - base;
    let peak = 0.4;
    for (const v of shifted) peak = Math.max(peak, Math.abs(v));
    const pxPerMv = Math.min(pxPerMm * 10, (h * 0.42) / peak);
    drawTrace(ctx, shifted, 0, data.length, 0, w / data.length, h * 0.56, pxPerMv, colors.trace, 1.4);
    for (const l of LINES) {
      const v = cal[l.key];
      if (v === null) continue;
      const x = xOf(v);
      ctx.strokeStyle = l.color;
      ctx.lineWidth = edit ? 1.8 : 1.2;
      ctx.setLineDash(edit ? [] : [4, 3]);
      ctx.beginPath(); ctx.moveTo(x, 12); ctx.lineTo(x, h); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = l.color;
      ctx.font = "600 10px Inter Variable, Inter, sans-serif";
      ctx.fillText(l.label, x - 3, 10);
    }
    ctx.fillStyle = colors.label;
    ctx.font = "600 11px Inter Variable, Inter, sans-serif";
    ctx.fillText(leadLabel(lead), 6, h - 6);
  }, [w, h, data, fs, r, cal, edit, colors, resolvedTheme, lead, msTotal]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (x: number): Key | null => {
    let best: Key | null = null, dist = 9;
    for (const l of LINES) {
      const v = cal[l.key];
      if (v === null) continue;
      const d = Math.abs(xOf(v) - x);
      if (d < dist) { dist = d; best = l.key; }
    }
    return best;
  };

  return (
    <div ref={wrap} className={cn("overflow-hidden rounded-lg border border-black/5 dark:border-white/5", quality && quality !== "good" && "ring-2 ring-warning/50")}>
      <canvas ref={ref} className={edit ? "cursor-ew-resize touch-none" : undefined}
        onPointerDown={(e) => { if (!edit) return; const x = e.clientX - ref.current!.getBoundingClientRect().left; drag.current = pick(x); if (drag.current) (e.target as Element).setPointerCapture(e.pointerId); }}
        onPointerMove={(e) => { if (!edit || !drag.current) return; const x = e.clientX - ref.current!.getBoundingClientRect().left; onDrag(drag.current, Math.round(msOf(x))); }}
        onPointerUp={() => { drag.current = null; }} />
    </div>
  );
}

export function MedianBeats({ beats, fs, r, calipers, onChange, edit = false, leadQuality = {} }: {
  beats: Record<string, Float32Array>; fs: number; r: number; calipers: Calipers; onChange?: (c: Calipers) => void; edit?: boolean;
  leadQuality?: Record<string, string>;
}) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {ORDER.map((l) => beats[l] && (
        <Panel key={l} lead={l} data={beats[l]} fs={fs} r={r} cal={calipers} edit={edit} quality={leadQuality[l]}
          onDrag={(k, ms) => onChange?.({ ...calipers, [k]: ms })} />
      ))}
    </div>
  );
}
