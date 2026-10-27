import { ChevronLeft, ChevronRight, Flag, HeartPulse, ShieldCheck, Waves } from "lucide-react";
import { useMemo, useState } from "react";
import { useParams } from "react-router";
import { Area, AreaChart, CartesianGrid, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { canSign, useDemo } from "@/app/demo-store";
import { StatusBadge } from "@/components/clinical/badges";
import { PatientHeader } from "@/components/clinical/PatientHeader";
import { BEAT_COLORS, HolterStrip } from "@/components/ecg/HolterStrip";
import { Badge, Button, Card, CardHeader, EmptyState, Segmented, Skeleton, Slider } from "@/components/ui";
import { useCatalog, useHolter } from "@/data/api";
import { BEAT_NAMES, RHYTHM_NAMES } from "@/data/clinical";
import { fmtClock, fmtDur, holterAnalytics, type HolterEvent } from "@/data/holter";
import { cn } from "@/lib/utils";

const RHYTHM_COLOR: Record<string, string> = { N: "bg-success/70", A: "bg-danger/80", O: "bg-warning/80", "~": "bg-muted-foreground/40" };
const EVENT_TONE: Record<HolterEvent["kind"], "danger" | "warning" | "info" | "neutral"> = { af: "danger", pvc_run: "danger", couplet: "warning", pause: "warning", max_hr: "info", min_hr: "info" };

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border bg-card/70 p-3">
      <div className="text-[0.72rem] text-muted-foreground">{label}</div>
      <div className="text-[1.25rem] font-semibold tracking-tight num">{value}</div>
      {sub && <div className="text-[0.7rem] text-muted-foreground">{sub}</div>}
    </div>
  );
}

export default function HolterReviewPage() {
  const { id } = useParams();
  const { data: c } = useCatalog();
  const { data, isLoading, error } = useHolter(id);
  const { review, updateReview, user, site } = useDemo();
  const [t, setT] = useState(0);
  const [span, setSpan] = useState<"10" | "30" | "60">("30");
  const [filter, setFilter] = useState<"all" | "af" | "ventricular" | "pause">("all");
  const a = useMemo(() => (data ? holterAnalytics(data.detail) : null), [data]);
  const h = c?.holters.find((x) => x.id === id);
  if (isLoading || !c) return <div className="space-y-4"><Skeleton className="h-14 w-96" /><Skeleton className="h-96" /></div>;
  if (error || !data || !a || !h) return <EmptyState title="Recording not found" description={String(error ?? "")} />;
  const p = c.patients.find((x) => x.id === h.patient_id)!;
  const r = data.detail.analysis.result;
  const m = r.measurements;
  const seconds = Number(span);
  const rows = seconds === 10 ? 1 : seconds === 30 ? 3 : 4;
  const rv = review(h.id);
  const jump = (s: number) => setT(Math.max(0, Math.min(a.dur - seconds, s - 2)));
  const events = a.events.filter((e) => filter === "all" || (filter === "af" && e.kind === "af") || (filter === "ventricular" && (e.kind === "pvc_run" || e.kind === "couplet")) || (filter === "pause" && e.kind === "pause"));
  const rates = a.hr.filter((x) => x.hr !== null).map((x) => x.hr!) ;
  return (
    <div className="animate-fade-in">
      <PatientHeader patient={p} chips={<><Badge tone="outline">Holter · {h.lead} · {fmtDur(a.dur)}</Badge><StatusBadge status={rv.status} /></>}
        actions={canSign(user) && rv.status !== "signed" ? (
          <Button variant="strong" onClick={() => { updateReview(h.id, { status: "signed", signedBy: user!.name, signedAt: new Date().toISOString() }, "Signed Holter report"); toast.success("Holter report signed and sent"); }}><ShieldCheck /> Sign Holter report</Button>
        ) : rv.status === "signed" ? <Badge tone="success"><ShieldCheck /> Signed by {rv.signedBy}</Badge> : undefined} />

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="Beats analysed" value={m.beats_analysed.toLocaleString()} sub={`${Math.round(m.usable_fraction * 100)}% of signal usable`} />
        <Stat label="Mean HR" value={`${Math.round(m.heart_rate_bpm)} bpm`} sub={rates.length ? `${Math.min(...rates)}–${Math.max(...rates)} (30 s means)` : undefined} />
        <Stat label="AF burden" value={`${Math.round(a.afBurden * 100)}%`} sub={a.episodes.length ? `${a.episodes.length} episode${a.episodes.length > 1 ? "s" : ""}` : "None"} />
        <Stat label="Ventricular ectopy" value={(m.beat_counts.V ?? 0).toLocaleString()} sub={`${(a.vBurden * 100).toFixed(1)}% of beats`} />
        <Stat label="Supraventricular" value={(m.beat_counts.S ?? 0).toLocaleString()} sub={`${(a.sBurden * 100).toFixed(1)}% of beats`} />
        <Stat label="Runs / couplets" value={`${a.events.filter((e) => e.kind === "pvc_run").length} / ${a.events.filter((e) => e.kind === "couplet").length}`} sub="Ventricular" />
        <Stat label="Pauses ≥ 2 s" value={String(a.events.filter((e) => e.kind === "pause").length)} sub={`Longest RR ${m.rr_max_s.toFixed(2)} s`} />
        <Stat label="Fusion beats" value={String(m.beat_counts.F ?? 0)} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-4">
          <Card>
            <CardHeader title="Heart rate and rhythm" description="30 s means · red band: AI-detected atrial fibrillation · click to jump" icon={<HeartPulse />} />
            <div className="h-44 px-2 pt-3">
              <ResponsiveContainer>
                <AreaChart data={a.hr} margin={{ top: 4, right: 12, left: -16, bottom: 0 }} onClick={(e) => { const lbl = e?.activeLabel; const pt = a.hr.find((x) => x.min === lbl); if (pt) jump(pt.t); }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  {a.episodes.map(([s0, s1]) => {
                    const x1 = a.hr.find((x) => x.t >= s0)?.min, x2 = [...a.hr].reverse().find((x) => x.t <= s1)?.min;
                    return x1 && x2 ? <ReferenceArea key={s0} x1={x1} x2={x2} fill="hsl(var(--danger))" fillOpacity={0.1} /> : null;
                  })}
                  <XAxis dataKey="min" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} interval={5} />
                  <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} domain={["auto", "auto"]} />
                  <RTooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 10, fontSize: 12 }} formatter={(v) => [`${v} bpm`, "HR"]} />
                  <ReferenceLine x={a.hr.find((x) => x.t >= t)?.min} stroke="hsl(var(--primary))" strokeDasharray="4 3" />
                  <Area isAnimationActive={false} type="monotone" dataKey="hr" stroke="hsl(var(--primary))" fill="hsl(var(--primary))" fillOpacity={0.12} strokeWidth={2} connectNulls />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="card-pad pt-2">
              <div className="text-label mb-1">Rhythm (30 s windows)</div>
              <div className="relative flex h-5 w-full overflow-hidden rounded-md bg-muted">
                {r.rhythm_segments.map((s) => (
                  <button key={s.start_s} title={`${fmtClock(s.start_s)} ${RHYTHM_NAMES[s.rhythm]} (${Math.round(s.probability * 100)}%)`} onClick={() => jump(s.start_s)}
                    className={cn("absolute top-0 h-full", RHYTHM_COLOR[s.rhythm])} style={{ left: `${(s.start_s / a.dur) * 100}%`, width: `${((s.end_s - s.start_s) / a.dur) * 50}%` }} />
                ))}
                {a.unusable.map(([s0, s1]) => <div key={s0} className="absolute top-0 h-full bg-slate-400/70" style={{ left: `${(s0 / a.dur) * 100}%`, width: `${((s1 - s0) / a.dur) * 100}%` }} />)}
                <div className="absolute top-0 h-full w-0.5 bg-foreground" style={{ left: `${(t / a.dur) * 100}%` }} />
              </div>
              <div className="mt-1.5 flex flex-wrap gap-3 text-[0.7rem] text-muted-foreground">
                {Object.entries(RHYTHM_NAMES).map(([k, v]) => <span key={k} className="flex items-center gap-1"><span className={cn("size-2.5 rounded-sm", RHYTHM_COLOR[k])} />{v}</span>)}
                <span className="flex items-center gap-1"><span className="size-2.5 rounded-sm bg-slate-400/70" />Unusable signal</span>
              </div>
            </div>
          </Card>

          <Card>
            <div className="flex flex-wrap items-center gap-2 px-[var(--card-pad)] pt-[var(--card-pad)]">
              <Waves className="size-4 text-primary" />
              <span className="text-[0.95rem] font-semibold">{fmtClock(t)} – {fmtClock(t + seconds)}</span>
              <span className="text-xs text-muted-foreground">25 mm/s · 10 mm/mV · {h.lead}</span>
              <div className="ml-auto flex items-center gap-1.5">
                <Segmented size="sm" value={span} onChange={setSpan} options={[{ value: "10", label: "10 s" }, { value: "30", label: "30 s" }, { value: "60", label: "60 s" }]} />
                <Button size="icon-sm" variant="secondary" aria-label="Earlier" onClick={() => setT((x) => Math.max(0, x - seconds))}><ChevronLeft /></Button>
                <Button size="icon-sm" variant="secondary" aria-label="Later" onClick={() => setT((x) => Math.min(a.dur - seconds, x + seconds))}><ChevronRight /></Button>
              </div>
            </div>
            <div className="px-[var(--card-pad)] pt-3">
              <Slider value={[t]} min={0} max={Math.max(0, a.dur - seconds)} step={1} onValueChange={([v]) => setT(v)} aria-label="Position in recording" />
            </div>
            <div className="card-pad">
              <HolterStrip signal={data.signal} fs={data.detail.fs} start={t} seconds={seconds} rows={rows} beats={r.beats} unusable={a.unusable}
                onBeatClick={(b) => toast(`${BEAT_NAMES[b.class]} beat at ${fmtClock(b.time_s)}`, { description: `AI probability ${Math.round(b.probability * 100)}% (${b.confidence}). Relabelling beats is part of the full review workflow.` })} />
              <div className="mt-2 flex flex-wrap gap-3 text-[0.72rem] text-muted-foreground">
                {Object.entries(BEAT_COLORS).map(([k, col]) => <span key={k} className="flex items-center gap-1"><span className="font-bold" style={{ color: col }}>{k}</span>{BEAT_NAMES[k]}</span>)}
                <span>· numbers: RR interval (ms); bold ≥ 2 s</span>
              </div>
            </div>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader title="Events" description="Found by the AI · click to open the strip" icon={<Flag />} />
            <div className="px-[var(--card-pad)] pt-3">
              <Segmented size="sm" value={filter} onChange={setFilter} options={[{ value: "all", label: "All" }, { value: "af", label: "AF" }, { value: "ventricular", label: "Ventricular" }, { value: "pause", label: "Pauses" }]} />
            </div>
            <div className="card-pad max-h-[560px] space-y-1.5 overflow-y-auto">
              {events.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">No events of this type.</p>}
              {events.map((e) => (
                <button key={`${e.kind}-${e.start}`} onClick={() => jump(e.start)} className={cn("flex w-full items-center gap-2 rounded-lg border bg-card/70 px-3 py-2 text-left text-[0.82rem] transition-colors hover:border-primary/40", t <= e.start && e.start < t + seconds && "border-primary/50 bg-primary-soft/40")}>
                  <Badge tone={EVENT_TONE[e.kind]}>{fmtClock(e.start)}</Badge>
                  <span className="font-medium">{e.label}</span>
                  <span className="ml-auto text-[0.75rem] text-muted-foreground">{e.detail}</span>
                </button>
              ))}
            </div>
          </Card>
          {site.showReference && <Card className="p-4 text-[0.8rem]">
            <div className="mb-1 flex items-center gap-1.5 font-semibold"><ShieldCheck className="size-4 text-success" /> Checked against the reference cardiologists</div>
            <p className="text-muted-foreground">
              {h.source.dataset} record {h.source.record} ({h.source.role}) has every beat labelled by cardiologists. The AI found {(a.agreement.detected * 100).toFixed(1)}% of their {a.agreement.refBeats.toLocaleString()} beats and gave {(a.agreement.sameClass * 100).toFixed(1)}% of them the same class
              {a.agreement.vSensitivity !== null && <> · ventricular beats found: {(a.agreement.vSensitivity * 100).toFixed(1)}% of {a.agreement.vRef}</>}. 
            </p>
          </Card>}
        </div>
      </div>
    </div>
  );
}
