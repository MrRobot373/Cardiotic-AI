/** ECG paper: colours and grid drawing shared by every waveform view. */

export type PaperStyle = "pink" | "green" | "grey";

export interface PaperColors {
  bg: string;
  minor: string;
  major: string;
  trace: string;
  label: string;
  accent: string;
}

export function paperColors(style: PaperStyle, dark: boolean): PaperColors {
  if (dark) {
    const tint = { pink: "255,110,110", green: "90,210,140", grey: "160,170,190" }[style];
    return { bg: "#0d1424", minor: `rgba(${tint},0.10)`, major: `rgba(${tint},0.24)`, trace: "#e6ebf5", label: "#9fb0cc", accent: "#6ea8ff" };
  }
  return {
    pink: { bg: "#fffafa", minor: "#f8dede", major: "#efb7b7", trace: "#111827", label: "#334155", accent: "#246BFD" },
    green: { bg: "#f8fffa", minor: "#d9f1e1", major: "#a9dcbb", trace: "#0f172a", label: "#334155", accent: "#246BFD" },
    grey: { bg: "#ffffff", minor: "#eceff4", major: "#cdd4df", trace: "#0f172a", label: "#334155", accent: "#246BFD" },
  }[style];
}

/** Draw the 1 mm / 5 mm grid over a region (pixel coordinates). */
export function drawGrid(ctx: CanvasRenderingContext2D, x0: number, y0: number, w: number, h: number, pxPerMm: number, c: PaperColors) {
  ctx.fillStyle = c.bg;
  ctx.fillRect(x0, y0, w, h);
  const lines = (step: number, color: string, width: number) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.beginPath();
    for (let x = x0; x <= x0 + w + 0.5; x += step) {
      ctx.moveTo(Math.round(x) + 0.5, y0);
      ctx.lineTo(Math.round(x) + 0.5, y0 + h);
    }
    for (let y = y0; y <= y0 + h + 0.5; y += step) {
      ctx.moveTo(x0, Math.round(y) + 0.5);
      ctx.lineTo(x0 + w, Math.round(y) + 0.5);
    }
    ctx.stroke();
  };
  if (pxPerMm >= 2.2) lines(pxPerMm, c.minor, 1);
  lines(pxPerMm * 5, c.major, 1);
}

/** Polyline of samples [from, to) mapped into a box: x by time, y by mV around a baseline. */
export function drawTrace(
  ctx: CanvasRenderingContext2D, data: Float32Array, from: number, to: number,
  x0: number, pxPerSample: number, yBase: number, pxPerMv: number, color: string, width = 1.25,
) {
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineJoin = "round";
  ctx.beginPath();
  const a = Math.max(0, Math.floor(from));
  const b = Math.min(data.length, Math.ceil(to));
  // decimate to ~1 point per pixel column while keeping peaks (min/max per column)
  const perPx = 1 / pxPerSample;
  if (perPx > 2) {
    let first = true;
    for (let px = 0; px < (b - a) * pxPerSample; px++) {
      const s0 = a + Math.floor(px * perPx);
      const s1 = Math.min(b, a + Math.floor((px + 1) * perPx));
      let lo = Infinity, hi = -Infinity;
      for (let s = s0; s < s1; s++) { const v = data[s]; if (v < lo) lo = v; if (v > hi) hi = v; }
      if (lo === Infinity) continue;
      const x = x0 + px;
      if (first) { ctx.moveTo(x, yBase - hi * pxPerMv); first = false; } else ctx.lineTo(x, yBase - hi * pxPerMv);
      ctx.lineTo(x, yBase - lo * pxPerMv);
    }
  } else {
    for (let s = a; s < b; s++) {
      const x = x0 + (s - from) * pxPerSample;
      const y = yBase - data[s] * pxPerMv;
      if (s === a) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
  }
  ctx.stroke();
}

/** 1 mV, 200 ms calibration pulse. */
export function drawCalibration(ctx: CanvasRenderingContext2D, x: number, yBase: number, pxPerMm: number, pxPerMv: number, color: string) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.25;
  ctx.beginPath();
  ctx.moveTo(x, yBase);
  ctx.lineTo(x + pxPerMm, yBase);
  ctx.lineTo(x + pxPerMm, yBase - pxPerMv);
  ctx.lineTo(x + pxPerMm * 4, yBase - pxPerMv);
  ctx.lineTo(x + pxPerMm * 4, yBase);
  ctx.lineTo(x + pxPerMm * 5, yBase);
  ctx.stroke();
}

export function setupCanvas(canvas: HTMLCanvasElement, w: number, h: number) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;
  const ctx = canvas.getContext("2d")!;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

export const LEAD_LABEL: Record<string, string> = { AVR: "aVR", AVL: "aVL", AVF: "aVF" };
export const leadLabel = (l: string) => LEAD_LABEL[l] ?? l;
