/** Holter summaries computed from the engine's beat and rhythm output. */
import type { Beat, HolterDetail } from "./types";

export interface HolterEvent {
  kind: "af" | "pvc_run" | "couplet" | "pause" | "max_hr" | "min_hr";
  start: number;
  end: number;
  label: string;
  detail: string;
}

export function holterAnalytics(d: HolterDetail) {
  const r = d.analysis.result;
  const beats = r.beats;
  const dur = d.n_samples / d.fs;
  // heart rate per 30 s bin from all beats
  const bin = 30;
  const hr: { t: number; min: string; hr: number | null; af: boolean }[] = [];
  for (let t = 0; t < dur; t += bin) {
    const inBin = beats.filter((b) => b.time_s >= t && b.time_s < t + bin);
    let rate: number | null = null;
    if (inBin.length > 2) rate = (60 * (inBin.length - 1)) / (inBin[inBin.length - 1].time_s - inBin[0].time_s);
    const af = r.rhythm_segments.some((s) => s.rhythm === "A" && s.start_s < t + bin && s.end_s > t);
    hr.push({ t, min: `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`, hr: rate ? Math.round(rate) : null, af });
  }
  // AF episodes: merge overlapping AF windows
  const episodes: [number, number][] = [];
  for (const s of r.rhythm_segments.filter((x) => x.rhythm === "A")) {
    const last = episodes[episodes.length - 1];
    if (last && s.start_s <= last[1]) last[1] = Math.max(last[1], s.end_s); else episodes.push([s.start_s, s.end_s]);
  }
  const afSeconds = episodes.reduce((a, [x, y]) => a + (y - x), 0);
  const events: HolterEvent[] = episodes.map(([a, b]) => ({ kind: "af", start: a, end: b, label: "Atrial fibrillation", detail: `${fmtDur(b - a)}` }));
  // ventricular runs
  let i = 0;
  while (i < beats.length) {
    if (beats[i].class !== "V") { i++; continue; }
    let j = i;
    while (j + 1 < beats.length && beats[j + 1].class === "V") j++;
    const n = j - i + 1;
    if (n >= 2) {
      const rate = n > 1 ? Math.round((60 * (n - 1)) / (beats[j].time_s - beats[i].time_s)) : 0;
      events.push({ kind: n >= 3 ? "pvc_run" : "couplet", start: beats[i].time_s, end: beats[j].time_s, label: n >= 3 ? `Ventricular run ×${n}` : "Ventricular couplet", detail: `${rate} bpm` });
    }
    i = j + 1;
  }
  // pauses
  for (let k = 1; k < beats.length; k++) {
    const rr = beats[k].time_s - beats[k - 1].time_s;
    if (rr >= 2) events.push({ kind: "pause", start: beats[k - 1].time_s, end: beats[k].time_s, label: "Pause", detail: `${rr.toFixed(2)} s` });
  }
  const rates = hr.filter((h) => h.hr !== null) as { t: number; hr: number }[];
  if (rates.length) {
    const mx = rates.reduce((a, b) => (b.hr > a.hr ? b : a)), mn = rates.reduce((a, b) => (b.hr < a.hr ? b : a));
    events.push({ kind: "max_hr", start: mx.t, end: mx.t + bin, label: "Maximum heart rate", detail: `${mx.hr} bpm (30 s mean)` });
    events.push({ kind: "min_hr", start: mn.t, end: mn.t + bin, label: "Minimum heart rate", detail: `${mn.hr} bpm (30 s mean)` });
  }
  events.sort((a, b) => a.start - b.start);
  const counts = r.measurements.beat_counts;
  const total = beats.length || 1;
  return {
    dur, hr, events, afSeconds, episodes,
    afBurden: afSeconds / dur,
    vBurden: (counts.V ?? 0) / total,
    sBurden: (counts.S ?? 0) / total,
    unusable: r.quality_segments.filter((q) => q.quality === "unusable").map((q) => [q.start_s, q.end_s] as [number, number]),
    agreement: agreement(beats, d.reference_beats),
  };
}

/** Beat-by-beat agreement with the dataset cardiologists (150 ms match window) — demo transparency only. */
function agreement(beats: Beat[], ref: { t: number; c: string }[]) {
  const r = ref.filter((x) => ["N", "S", "V", "F"].includes(x.c));
  let j = 0, matched = 0, same = 0;
  const vRef = r.filter((x) => x.c === "V").length;
  let vHit = 0;
  for (const x of r) {
    while (j < beats.length && beats[j].time_s < x.t - 0.15) j++;
    if (j < beats.length && Math.abs(beats[j].time_s - x.t) <= 0.15) {
      matched++;
      if (beats[j].class === x.c) same++;
      if (x.c === "V" && beats[j].class === "V") vHit++;
    }
  }
  return { refBeats: r.length, detected: matched / (r.length || 1), sameClass: same / (matched || 1), vSensitivity: vRef ? vHit / vRef : null, vRef };
}

export function fmtDur(s: number) {
  if (s < 60) return `${Math.round(s)} s`;
  const m = Math.floor(s / 60), sec = Math.round(s % 60);
  return sec ? `${m} min ${sec} s` : `${m} min`;
}

export function fmtClock(s: number) {
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}
