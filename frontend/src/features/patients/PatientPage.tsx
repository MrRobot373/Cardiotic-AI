import { Activity, FileHeart, LineChart as LineIcon } from "lucide-react";
import { Link, useParams } from "react-router";
import { CartesianGrid, Legend, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { PriorityBadge, StatusBadge } from "@/components/clinical/badges";
import { PatientHeader } from "@/components/clinical/PatientHeader";
import { Badge, Button, Card, CardHeader, EmptyState, Skeleton } from "@/components/ui";
import { statementName } from "@/data/clinical";
import { useWorkItems } from "@/data/derived";
import { fmtDate, fmtDateTime } from "@/lib/utils";

export default function PatientPage() {
  const { id } = useParams();
  const { items, catalog, isLoading } = useWorkItems();
  if (isLoading || !catalog) return <Skeleton className="h-96" />;
  const patient = catalog.patients.find((p) => p.id === id);
  if (!patient) return <EmptyState title="Patient not found" />;
  const ecgs = items.filter((i) => i.patient.id === id).sort((a, b) => a.ecg.recorded_at.localeCompare(b.ecg.recorded_at));
  const holters = catalog.holters.filter((h) => h.patient_id === id);
  const trend = ecgs.map((i) => ({
    date: fmtDate(i.ecg.recorded_at, "d MMM"),
    HR: i.ecg.measurements.heart_rate_bpm ? Math.round(i.ecg.measurements.heart_rate_bpm) : null,
    QRS: i.ecg.measurements.qrs_ms ? Math.round(i.ecg.measurements.qrs_ms) : null,
    QTc: i.ecg.measurements.qtc_bazett_ms ? Math.round(i.ecg.measurements.qtc_bazett_ms) : null,
    PR: i.ecg.measurements.pr_ms ? Math.round(i.ecg.measurements.pr_ms) : null,
  }));
  return (
    <div className="animate-fade-in">
      <PatientHeader patient={patient} chips={<Badge tone="outline">{ecgs.length} ECGs · {holters.length} Holter</Badge>}
        actions={ecgs.length > 0 && <Button variant="strong" asChild><Link to={`/ecg/${ecgs[ecgs.length - 1].ecg.id}`}>Open latest ECG</Link></Button>} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="min-w-0 space-y-4">
          {ecgs.length > 1 && (
            <Card>
              <CardHeader title="Trends" description="From each ECG's AI measurements · shaded: usual adult range" icon={<LineIcon />} />
              <div className="grid gap-4 p-[var(--card-pad)] lg:grid-cols-2">
                {[["QTc", "QTc (Bazett), ms", [350, 450], "#DC2626"], ["QRS", "QRS duration, ms", [70, 120], "#059669"], ["HR", "Heart rate, bpm", [60, 100], "#246BFD"], ["PR", "PR interval, ms", [120, 200], "#7C3AED"]].map(([k, label, band, color]) => (
                  <div key={k as string}>
                    <div className="mb-1 text-[0.78rem] font-medium">{label as string}</div>
                    <div className="h-40">
                      <ResponsiveContainer>
                        <LineChart data={trend} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                          <ReferenceArea y1={(band as number[])[0]} y2={(band as number[])[1]} fill="hsl(var(--success))" fillOpacity={0.08} />
                          <XAxis dataKey="date" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                          <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} domain={["auto", "auto"]} />
                          <RTooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 10, fontSize: 12 }} />
                          <Line isAnimationActive={false} type="monotone" dataKey={k as string} stroke={color as string} strokeWidth={2} dot={{ r: 3 }} connectNulls />
                          {k === "QTc" && <Legend wrapperStyle={{ display: "none" }} />}
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
          <Card>
            <CardHeader title="ECG history" description="Newest first" icon={<FileHeart />} />
            <div className="card-pad space-y-2">
              {[...ecgs].reverse().map((i) => (
                <Link key={i.ecg.id} to={`/ecg/${i.ecg.id}`} className="block rounded-xl border bg-card/70 p-3 transition-colors hover:border-primary/40">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{fmtDateTime(i.ecg.recorded_at)}</span>
                    <span className="text-[0.78rem] text-muted-foreground">{i.ecg.location}</span>
                    <PriorityBadge priority={i.priority} /><StatusBadge status={i.review.status} className="ml-auto" />
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1">{i.ecg.statements.filter((s) => !s.statement.startsWith("SUPER_")).map((s) => <Badge key={s.statement}>{statementName(s.statement)}</Badge>)}</div>
                  <div className="mt-1.5 flex gap-4 text-[0.75rem] text-muted-foreground num">
                    <span>HR {i.ecg.measurements.heart_rate_bpm ? Math.round(i.ecg.measurements.heart_rate_bpm) : "—"}</span>
                    <span>PR {i.ecg.measurements.pr_ms ? Math.round(i.ecg.measurements.pr_ms) : "—"}</span>
                    <span>QRS {i.ecg.measurements.qrs_ms ? Math.round(i.ecg.measurements.qrs_ms) : "—"}</span>
                    <span>QTc {i.ecg.measurements.qtc_bazett_ms ? Math.round(i.ecg.measurements.qtc_bazett_ms) : "—"}</span>
                  </div>
                </Link>
              ))}
              {ecgs.length === 0 && <EmptyState compact title="No 12-lead ECGs" />}
            </div>
          </Card>
        </div>
        <div className="space-y-4">
          <Card>
            <CardHeader title="Holter & monitoring" icon={<Activity />} />
            <div className="card-pad space-y-2">
              {holters.length === 0 && <p className="text-sm text-muted-foreground">No long recordings.</p>}
              {holters.map((h) => (
                <Link key={h.id} to={`/holter/${h.id}`} className="block rounded-xl border bg-card/70 p-3 hover:border-primary/40">
                  <div className="font-medium">{Math.round(h.duration_s / 60)} min recording · {fmtDateTime(h.recorded_at)}</div>
                  <ul className="mt-1 list-disc pl-4 text-[0.78rem] text-muted-foreground">{h.findings.slice(0, 3).map((f) => <li key={f}>{f}</li>)}</ul>
                </Link>
              ))}
            </div>
          </Card>
          <Card className="p-4 text-[0.78rem] text-muted-foreground">
            <div className="font-semibold text-foreground">Data source</div>
            Signals: {Array.from(new Set([...ecgs.map((i) => i.ecg.source.dataset), ...holters.map((h) => h.source.dataset)])).join(", ")} — real recordings, the time between this patient's ECGs is real. Name and record number are fictitious.
          </Card>
        </div>
      </div>
    </div>
  );
}
