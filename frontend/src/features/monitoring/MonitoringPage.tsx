import { Flag, Info, Pause, Play, WifiOff, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { useAppearance } from "@/app/appearance";
import { Badge, Button, Card, PageHeader, Segmented, Tooltip } from "@/components/ui";
import { useHolter } from "@/data/api";
import type { Beat } from "@/data/types";
import { cn } from "@/lib/utils";

interface Bed {
  id: string;
  unit: "OT" | "ICU";
  patient: string;
  holter: string;
  offset: number;
  state: "ok" | "flag" | "diathermy" | "offline";
  flag?: string;
  spo2: number;
  abp?: string;
}

const BEDS: Bed[] = [
  { id: "OT-1", unit: "OT", patient: "Meera Kulkarni", holter: "H003", offset: 120, state: "ok", spo2: 99, abp: "118/72" },
  { id: "OT-2", unit: "OT", patient: "Sanjay Patil", holter: "H002", offset: 600, state: "flag", flag: "Frequent ventricular ectopics (bigeminy)", spo2: 97, abp: "104/66" },
  { id: "OT-3", unit: "OT", patient: "Fatima Shaikh", holter: "H003", offset: 900, state: "diathermy", spo2: 98, abp: "122/78" },
  { id: "ICU-4", unit: "ICU", patient: "Vikram Joshi", holter: "H001", offset: 60, state: "flag", flag: "Possible atrial fibrillation · 14 min", spo2: 95, abp: "131/84" },
  { id: "ICU-5", unit: "ICU", patient: "Lata Deshmukh", holter: "H002", offset: 1400, state: "ok", spo2: 100, abp: "126/70" },
  { id: "ICU-6", unit: "ICU", patient: "Arjun Nair", holter: "H001", offset: 1200, state: "offline", spo2: 0 },
];

function MonitorTrace({ signal, fs, offset, beats, running, noisy, onHr }: {
  signal: Float32Array; fs: number; offset: number; beats: Beat[]; running: boolean; noisy?: boolean; onHr: (hr: number | null) => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const lastHr = useRef(0);
  const { resolvedTheme } = useAppearance();
  const t0 = useRef(performance.now());
  const pausedAt = useRef(0);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    let raf = 0;
    const win = 6;
    const draw = () => {
      const w = c.clientWidth, h = c.clientHeight;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (c.width !== Math.round(w * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
      const ctx = c.getContext("2d")!;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const elapsed = running ? (performance.now() - t0.current) / 1000 : pausedAt.current;
      if (running) pausedAt.current = elapsed;
      const now = offset + (elapsed % 600);
      const cycleStart = now - (now % win);
      const sweep = (now % win) / win;
      ctx.fillStyle = resolvedTheme === "dark" ? "#0b1220" : "#f8fafc";
      ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = noisy ? "#d97706" : "#10b981";
      ctx.lineWidth = 1.6;
      // newest part (this cycle) up to the sweep line, oldest part (previous cycle) after a small gap
      for (const [a, b, start] of [[0, sweep, cycleStart], [sweep + 0.03, 1, cycleStart - win]] as const) {
        if (b <= a) continue;
        ctx.beginPath();
        const n = Math.max(2, Math.floor((b - a) * w));
        for (let k = 0; k <= n; k++) {
          const f = a + ((b - a) * k) / n;
          const idx = Math.floor((start + f * win) * fs);
          let v = signal[Math.max(0, Math.min(signal.length - 1, idx))] ?? 0;
          if (noisy) v += Math.sin(idx * 0.9) * 0.6 + (Math.sin(idx * 0.37) > 0.6 ? 0.8 : 0);
          const y = h * 0.6 - v * h * 0.28;
          if (k === 0) ctx.moveTo(f * w, y); else ctx.lineTo(f * w, y);
        }
        ctx.stroke();
      }
      if (performance.now() - lastHr.current > 1000) {  // the number updates once a second, like a monitor
        lastHr.current = performance.now();
        const recent = beats.filter((x) => x.time_s > now - 8 && x.time_s <= now);
        onHr(recent.length > 2 ? Math.round((60 * (recent.length - 1)) / (recent[recent.length - 1].time_s - recent[0].time_s)) : null);
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [signal, fs, offset, beats, running, noisy, resolvedTheme, onHr]);
  return <canvas ref={ref} className="h-24 w-full rounded-lg border border-black/5 dark:border-white/5" aria-label="Live ECG trace" />;
}

function BedTile({ bed, running }: { bed: Bed; running: boolean }) {
  const { data } = useHolter(bed.state === "offline" ? undefined : bed.holter);
  const [hr, setHr] = useState<number | null>(null);
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold">{bed.id}</div>
          <div className="text-[0.78rem] text-muted-foreground">{bed.patient}</div>
        </div>
        {bed.state === "flag" && <Badge tone="primary" className="bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300"><Flag /> 1 review flag</Badge>}
        {bed.state === "ok" && <Badge tone="neutral">No flags</Badge>}
        {bed.state === "diathermy" && <Badge tone="warning"><Zap /> Diathermy — analysis paused</Badge>}
        {bed.state === "offline" && <Badge tone="danger"><WifiOff /> Assist offline</Badge>}
      </div>
      {bed.state === "offline" ? (
        <div className="flex h-24 items-center justify-center rounded-lg border border-dashed bg-[repeating-linear-gradient(135deg,transparent,transparent_8px,hsl(var(--muted))_8px,hsl(var(--muted))_16px)] px-4 text-center text-[0.78rem] text-muted-foreground">
          Stream lost 00:14 ago. No data is shown; check the bedside monitor.
        </div>
      ) : data ? (
        <MonitorTrace signal={data.signal} fs={data.detail.fs} offset={bed.offset} beats={data.detail.analysis.result.beats} running={running} noisy={bed.state === "diathermy"} onHr={setHr} />
      ) : <div className="skeleton h-24 w-full" />}
      <div className="mt-3 flex items-end justify-between gap-3">
        <div className="flex gap-5">
          <div><div className="text-label">HR · bpm</div><div className={cn("text-[1.9rem] font-semibold leading-none num", bed.state === "offline" || bed.state === "diathermy" ? "text-muted-foreground" : "text-success")}>{bed.state === "offline" || bed.state === "diathermy" ? "—" : hr ?? "—"}</div></div>
          <div><div className="text-label">SpO₂ · %</div><div className="text-[1.9rem] font-semibold leading-none text-info num">{bed.spo2 || "—"}</div></div>
          {bed.abp && <div><div className="text-label">ABP</div><div className="text-[1.15rem] font-semibold leading-none text-danger num">{bed.abp}</div></div>}
        </div>
        {bed.state === "ok" && <Badge tone="success">Analysable</Badge>}
      </div>
      {bed.flag && (
        <div className="mt-3 flex items-center justify-between gap-2 rounded-lg bg-violet-50 px-3 py-2 text-[0.78rem] text-violet-800 dark:bg-violet-500/10 dark:text-violet-200">
          <span>{bed.flag}</span>
          <Button size="xs" variant="ghost" asChild><Link to={`/holter/${bed.holter}`}>Review</Link></Button>
        </div>
      )}
    </Card>
  );
}

export default function MonitoringPage() {
  const [unit, setUnit] = useState<"all" | "OT" | "ICU">("all");
  const [running, setRunning] = useState(true);
  return (
    <div className="animate-fade-in">
      <PageHeader eyebrow="Live Assist · in development"
        title="Monitoring"
        description="Advisory review flags for connected OT and ICU beds. This board never replaces, delays or silences the bedside monitor's alarms, and it looks different from them on purpose."
        actions={<>
          <Segmented value={unit} onChange={setUnit} options={[{ value: "all", label: "All beds" }, { value: "OT", label: "OT" }, { value: "ICU", label: "ICU" }]} />
          <Tooltip content={running ? "Pause traces" : "Resume traces"}><Button size="icon" variant="secondary" onClick={() => setRunning((r) => !r)} aria-label="Pause or resume">{running ? <Pause /> : <Play />}</Button></Tooltip>
        </>} />
      <div className="mb-4 flex items-start gap-2 rounded-xl border border-dashed bg-card/60 p-3 text-[0.78rem] text-muted-foreground">
        <Info className="mt-0.5 size-4 shrink-0" />
        Heart rate is computed from the AI's beat detections on the monitor's ECG feed. SpO₂ and blood pressure are passed through from the bedside monitor unchanged.
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {BEDS.filter((b) => unit === "all" || b.unit === unit).map((b) => <BedTile key={b.id} bed={b} running={running} />)}
      </div>
    </div>
  );
}
