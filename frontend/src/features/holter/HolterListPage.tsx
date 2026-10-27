import { Activity } from "lucide-react";
import { Link } from "react-router";
import { useDemo } from "@/app/demo-store";
import { Avatar, Badge, Button, Card, PageHeader } from "@/components/ui";
import { useCatalog } from "@/data/api";
import { ageLabel } from "@/data/clinical";
import { fmtDateTime } from "@/lib/utils";

export default function HolterListPage() {
  const { data: c } = useCatalog();
  const { site } = useDemo();
  return (
    <div className="animate-fade-in">
      <PageHeader title="Holter & long recordings" description="Every beat classified and every 30 s window given a rhythm by the AI. The reader confirms events instead of scrolling through hours of ECG." />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {c?.holters.map((h) => {
          const p = c.patients.find((x) => x.id === h.patient_id)!;
          const m = h.measurements;
          return (
            <Card key={h.id} className="flex flex-col p-5">
              <div className="flex items-center gap-3">
                <Avatar name={p.name} />
                <div className="min-w-0">
                  <div className="font-semibold">{p.name}</div>
                  <div className="text-[0.75rem] text-muted-foreground">{p.mrn} · {ageLabel(p.age, p.age_90_plus)} {p.sex} · {fmtDateTime(h.recorded_at)}</div>
                </div>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                <div className="rounded-lg bg-subtle p-2"><div className="text-[0.68rem] text-muted-foreground">Duration</div><div className="font-semibold num">{Math.round(h.duration_s / 60)} min</div></div>
                <div className="rounded-lg bg-subtle p-2"><div className="text-[0.68rem] text-muted-foreground">Beats</div><div className="font-semibold num">{m.beats_analysed.toLocaleString()}</div></div>
                <div className="rounded-lg bg-subtle p-2"><div className="text-[0.68rem] text-muted-foreground">Mean HR</div><div className="font-semibold num">{Math.round(m.heart_rate_bpm)}</div></div>
              </div>
              <ul className="mt-3 flex-1 space-y-1 text-[0.8rem]">{h.findings.map((f) => <li key={f} className="flex gap-1.5"><Activity className="mt-0.5 size-3.5 shrink-0 text-primary" />{f}</li>)}</ul>
              <div className="mt-4 flex items-center justify-between">
                {site.showReference ? <Badge tone="outline">{h.source.dataset} {h.source.record}</Badge> : <span />}
                <Button size="sm" variant="strong" asChild><Link to={`/holter/${h.id}`}>Review</Link></Button>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
