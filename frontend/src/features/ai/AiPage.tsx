import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BrainCircuit, CheckCircle2, CircleAlert, Cpu, Fingerprint, ShieldCheck } from "lucide-react";
import { Link } from "react-router";
import { Badge, Button, Card, PageHeader, Skeleton } from "@/components/ui";
import { useCatalog } from "@/data/api";

interface Validation {
  models: { id: string; name: string; version: string; kind: string; task: string; tested_on: string; metrics: [string, string][]; limits: string[] }[];
  engine: { version: string; models_version: string; passed: boolean; ecgs: number; beats: number; max_prob_diff: number };
  source: string;
}

const PIPELINE = ["ECG signal", "Signal quality", "Heartbeats", "Beat types", "Rhythm", "Measurements", "Diagnostic statements", "Calibration", "Cardiologist review"];

export default function AiPage() {
  const { data: c } = useCatalog();
  const { data: v } = useQuery({ queryKey: ["validation"], staleTime: Infinity, queryFn: () => fetch(`${import.meta.env.BASE_URL}demo/validation.json`).then((r) => r.json() as Promise<Validation>) });
  return (
    <div className="animate-fade-in space-y-5">
      <PageHeader eyebrow="Transparency" title="AI models & validation"
        description="What each model does, what it was tested on, how well it did and where it is weak. Every number comes from patients the models never saw while being built." />
      <Card className="p-5">
        <div className="text-label mb-3">How an ECG flows through Cardiotic AI</div>
        <div className="flex flex-wrap items-center gap-1.5">
          {PIPELINE.map((s, i) => (
            <span key={s} className="flex items-center gap-1.5">
              <span className={i === PIPELINE.length - 1 ? "rounded-full bg-strong px-3 py-1 text-[0.8rem] font-medium text-strong-foreground" : "rounded-full border bg-card px-3 py-1 text-[0.8rem] font-medium"}>{s}</span>
              {i < PIPELINE.length - 1 && <ArrowRight className="size-3.5 text-muted-foreground" />}
            </span>
          ))}
        </div>
        <p className="mt-3 text-[0.8rem] text-muted-foreground">If a segment or lead is unusable, nothing is concluded from it. No large language model is used anywhere in measurement or diagnosis; every number traces back to points on the recording.</p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-5">
          <div className="flex items-center gap-2 font-semibold"><Fingerprint className="size-4 text-primary" /> Locked, versioned models</div>
          <p className="mt-1 text-[0.8rem] text-muted-foreground">The engine checks each model file's SHA-256 fingerprint at start-up and refuses to run if one was changed. Models never retrain themselves in the hospital.</p>
          <div className="mt-3 space-y-1 font-mono text-[0.7rem]">{c && Object.entries(c.engine.models).map(([k, m]) => <div key={k} className="flex justify-between gap-2"><span>{m.model}</span><span className="text-muted-foreground">{m.sha256.slice(0, 12)}…</span></div>)}</div>
        </Card>
        <Card className="p-5">
          <div className="flex items-center gap-2 font-semibold"><Cpu className="size-4 text-primary" /> On-premise, CPU only</div>
          <p className="mt-1 text-[0.8rem] text-muted-foreground">Runs on the hospital's own server; no patient data leaves the hospital. One CPU core: 27 ms per 12-lead ECG, about 1 minute for a 24-hour Holter. No GPU needed.</p>
        </Card>
        <Card className="p-5">
          <div className="flex items-center gap-2 font-semibold"><ShieldCheck className="size-4 text-primary" /> Same answers in research and product</div>
          {v ? <p className="mt-1 text-[0.8rem] text-muted-foreground">The deployed engine gave identical findings to the tested research pipeline on {v.engine.ecgs} real 12-lead ECGs and {v.engine.beats.toLocaleString()} Holter beats (probabilities within {v.engine.max_prob_diff.toExponential(0)}).</p> : <Skeleton className="mt-2 h-10" />}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {(v?.models ?? []).map((m) => (
          <Card key={m.id} className="p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 text-[1rem] font-semibold"><BrainCircuit className="size-4 text-primary" />{m.name}</div>
                <div className="text-[0.78rem] text-muted-foreground">{m.task}</div>
              </div>
              <Badge tone="outline" className="shrink-0">{m.version}</Badge>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
              {m.metrics.map(([k, val]) => <div key={k} className="rounded-lg bg-subtle p-2.5"><div className="text-[0.7rem] text-muted-foreground">{k}</div><div className="text-[1.05rem] font-semibold num">{val}</div></div>)}
            </div>
            <div className="mt-3 text-[0.75rem] text-muted-foreground"><span className="font-medium text-foreground">Tested on: </span>{m.tested_on} · {m.kind}</div>
            <ul className="mt-2 space-y-1">
              {m.limits.map((l) => <li key={l} className="flex gap-1.5 text-[0.78rem]"><CircleAlert className="mt-0.5 size-3.5 shrink-0 text-warning" />{l}</li>)}
            </ul>
          </Card>
        ))}
        {!v && [0, 1, 2, 3].map((k) => <Skeleton key={k} className="h-56" />)}
      </div>

      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 font-semibold"><CheckCircle2 className="size-4 text-success" /> Before clinical use</div>
            <p className="mt-1 max-w-3xl text-[0.8rem] text-muted-foreground">Public research data builds the models. A study on this hospital's own ECG machines and patients, labelled by its cardiologists, decides whether they are good enough. Thresholds are set per site. Regulatory clearance (CDSCO, FDA) is required for clinical use.</p>
          </div>
          <Button variant="secondary" asChild><Link to="/settings/site">Site operating points</Link></Button>
        </div>
      </Card>
      <p className="text-[0.7rem] text-muted-foreground">Source: {v?.source}. Research use only — not a medical device.</p>
    </div>
  );
}
