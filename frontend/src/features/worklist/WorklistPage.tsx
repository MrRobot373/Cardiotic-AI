import { Activity, AlertTriangle, ArrowRight, BrainCircuit, CheckCircle2, Clock3, Cpu, Inbox, Search, ShieldCheck, Waves } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { useDemo } from "@/app/demo-store";
import { PriorityBadge, StatusBadge } from "@/components/clinical/badges";
import { Avatar, Badge, Button, Card, CardHeader, EmptyState, Input, Segmented, Skeleton, Table, TBody, TD, TH, THead, TR } from "@/components/ui";
import { ageLabel, isGroup, qtcInterpretable, rangeFlag, statementName } from "@/data/clinical";
import { byPriorityThenTime, isOpen, useWorkItems, type WorkItem } from "@/data/derived";
import { cn, fmtRelative, greeting } from "@/lib/utils";

type Tab = "open" | "urgent" | "repeat" | "signed" | "all";

function Kpi({ icon, label, value, sub, tone }: { icon: React.ReactNode; label: string; value: React.ReactNode; sub: string; tone: string }) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-3">
        <div className={cn("flex size-10 items-center justify-center rounded-xl [&_svg]:size-5", tone)}>{icon}</div>
        <div className="min-w-0">
          <div className="text-[0.75rem] text-muted-foreground">{label}</div>
          <div className="text-[1.45rem] font-semibold leading-tight tracking-tight num">{value}</div>
        </div>
      </div>
      <div className="mt-2 text-[0.72rem] text-muted-foreground">{sub}</div>
    </Card>
  );
}

function Findings({ i }: { i: WorkItem }) {
  const f = i.ecg.statements.filter((s) => !isGroup(s.statement) && s.statement !== "SR").slice(0, 3);
  if (!f.length) return <span className="text-muted-foreground">Sinus rhythm</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {f.map((s) => <Badge key={s.statement} tone={s.confidence === "high" ? "neutral" : "outline"}>{statementName(s.statement)}</Badge>)}
    </div>
  );
}

export default function WorklistPage() {
  const { items, catalog, isLoading } = useWorkItems();
  const { user } = useDemo();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("open");
  const [q, setQ] = useState("");
  const open = useMemo(() => items.filter((i) => isOpen(i, items)), [items]);
  const rows = useMemo(() => {
    let r = items;
    if (tab === "open") r = open;
    if (tab === "urgent") r = open.filter((i) => i.priority === "critical" || i.priority === "urgent");
    if (tab === "repeat") r = items.filter((i) => i.review.status === "repeat");
    if (tab === "signed") r = items.filter((i) => i.review.status === "signed");
    const s = q.trim().toLowerCase();
    if (s) r = r.filter((i) => `${i.patient.name} ${i.patient.mrn} ${i.ecg.statements.map((x) => statementName(x.statement)).join(" ")}`.toLowerCase().includes(s));
    return [...r].sort(byPriorityThenTime);
  }, [items, open, tab, q]);

  if (isLoading || !catalog) return <div className="space-y-4"><Skeleton className="h-10 w-80" /><div className="grid gap-4 md:grid-cols-4">{[0, 1, 2, 3].map((k) => <Skeleton key={k} className="h-28" />)}</div><Skeleton className="h-96" /></div>;
  const urgent = open.filter((i) => i.priority === "critical" || i.priority === "urgent").length;
  const critical = open.filter((i) => i.priority === "critical").length;
  const signed = items.filter((i) => i.review.status === "signed").length;
  const quality = open.filter((i) => i.ecg.unusable_leads.length > 0).length;

  return (
    <div className="animate-fade-in space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="text-label mb-1.5">ECG reading room · {new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</div>
          <h1 className="text-[1.45rem] font-semibold tracking-tight">{greeting()}, {user?.name.split(" ").slice(0, 2).join(" ")}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Every ECG below was pre-read by Cardiotic AI and ordered by urgency. Nothing is reported until a cardiologist signs it.</p>
        </div>
        <Button variant="strong" onClick={() => { const n = [...open].sort(byPriorityThenTime)[0]; if (n) navigate(`/ecg/${n.ecg.id}`); }} disabled={!open.length}>
          Start reading <ArrowRight />
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={<Inbox />} label="To read" value={open.length} sub={`${items.length} ECGs in the last 30 days`} tone="bg-primary-soft text-primary-soft-foreground" />
        <Kpi icon={<AlertTriangle />} label="Critical / urgent" value={<>{critical} <span className="text-base font-normal text-muted-foreground">/ {urgent - critical}</span></>} sub="AI triage: read these first" tone="bg-danger-soft text-danger-foreground" />
        <Kpi icon={<CheckCircle2 />} label="Signed" value={signed} sub="Sent to HIS as HL7 ORU (simulated)" tone="bg-success-soft text-success-foreground" />
        <Kpi icon={<Cpu />} label="AI pre-read" value={<>27<span className="ml-1 text-base font-normal text-muted-foreground">ms</span></>} sub={`Median per ECG on one CPU core · ${quality} with an unusable lead`} tone="bg-info-soft text-info-foreground" />
      </div>

      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="min-w-0 overflow-hidden">
          <div className="flex flex-col gap-3 px-[var(--card-pad)] pt-[var(--card-pad)] md:flex-row md:items-center md:justify-between">
            <Segmented value={tab} onChange={setTab} options={[
              { value: "open", label: `To read · ${open.length}` }, { value: "urgent", label: `Critical & urgent · ${urgent}` },
              { value: "repeat", label: "Repeat requested" }, { value: "signed", label: "Signed" }, { value: "all", label: "All" },
            ]} />
            <Input icon={<Search />} placeholder="Patient, MRN or finding" value={q} onChange={(e) => setQ(e.target.value)} className="md:w-72" />
          </div>
          <div className="mt-3 overflow-x-auto">
            {rows.length > 0 && (
              <div className="divide-y md:hidden">
                {rows.map((i) => (
                  <Link key={i.ecg.id} to={`/ecg/${i.ecg.id}`} className="block px-[var(--card-pad)] py-3">
                    <div className="flex items-center gap-2">
                      <PriorityBadge priority={i.priority} />
                      <span className="truncate font-medium">{i.patient.name}</span>
                      <span className="ml-auto shrink-0 text-[0.72rem] text-muted-foreground">{fmtRelative(i.ecg.recorded_at)}</span>
                    </div>
                    <div className="mt-1.5"><Findings i={i} /></div>
                    <div className="mt-1.5 flex items-center gap-3 text-[0.72rem] text-muted-foreground">
                      <span>HR {i.ecg.measurements.heart_rate_bpm ? Math.round(i.ecg.measurements.heart_rate_bpm) : "—"}</span>
                      <span>QTc {i.ecg.measurements.qtc_bazett_ms ? Math.round(i.ecg.measurements.qtc_bazett_ms) : "—"}</span>
                      <StatusBadge status={i.review.status} className="ml-auto" />
                    </div>
                  </Link>
                ))}
              </div>
            )}
            {rows.length === 0 ? <EmptyState icon={<CheckCircle2 />} title="Nothing here" description={tab === "open" ? "All caught up — every ECG is signed." : "No ECGs match."} /> : (
              <Table className="hidden md:table">
                <THead>
                  <TR>
                    <TH className="w-28">Priority</TH><TH>Patient</TH><TH>AI findings</TH><TH className="text-right">Rate</TH><TH className="text-right">QTc</TH><TH>Recorded</TH><TH>Status</TH><TH />
                  </TR>
                </THead>
                <TBody>
                  {rows.map((i) => (
                    <TR key={i.ecg.id} className="cursor-pointer" onClick={() => navigate(`/ecg/${i.ecg.id}`)}>
                      <TD><PriorityBadge priority={i.priority} /><div className="mt-1 max-w-[9rem] truncate text-[0.68rem] text-muted-foreground" title={i.reason}>{i.reason}</div></TD>
                      <TD>
                        <div className="flex items-center gap-2.5">
                          <Avatar name={i.patient.name} size="sm" />
                          <div className="min-w-0">
                            <div className="truncate font-medium">{i.patient.name}</div>
                            <div className="text-[0.72rem] text-muted-foreground">{i.patient.mrn} · {ageLabel(i.patient.age, i.patient.age_90_plus)} {i.patient.sex}</div>
                          </div>
                        </div>
                      </TD>
                      <TD className="max-w-[22rem]"><Findings i={i} />{i.ecg.unusable_leads.length > 0 && <div className="mt-1 text-[0.68rem] text-warning-foreground">Unusable lead: {i.ecg.unusable_leads.join(", ")}</div>}</TD>
                      <TD className={cn("text-right num", rangeFlag("heart_rate_bpm", i.ecg.measurements.heart_rate_bpm) && "font-semibold text-warning-foreground")}>{i.ecg.measurements.heart_rate_bpm ? Math.round(i.ecg.measurements.heart_rate_bpm) : "—"}</TD>
                      <TD className={cn("text-right num", qtcInterpretable(i.ecg.measurements, i.ecg.statements) ? rangeFlag("qtc_bazett_ms", i.ecg.measurements.qtc_bazett_ms, i.patient.sex) && "font-semibold text-warning-foreground" : "text-muted-foreground")}
                        title={qtcInterpretable(i.ecg.measurements, i.ecg.statements) ? undefined : "Wide QRS or paced: QTc not interpretable"}>
                        {i.ecg.measurements.qtc_bazett_ms ? Math.round(i.ecg.measurements.qtc_bazett_ms) : "—"}{!qtcInterpretable(i.ecg.measurements, i.ecg.statements) && "*"}
                      </TD>
                      <TD className="whitespace-nowrap text-muted-foreground"><div>{fmtRelative(i.ecg.recorded_at)}</div><div className="text-[0.68rem]">{i.ecg.location}</div></TD>
                      <TD><StatusBadge status={i.review.status} /></TD>
                      <TD className="text-right"><Button size="xs" variant={i.review.status === "signed" ? "ghost" : "secondary"} asChild><Link to={`/ecg/${i.ecg.id}`} onClick={(e) => e.stopPropagation()}>{i.review.status === "signed" ? "View" : "Read"}</Link></Button></TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
            {rows.some((i) => !qtcInterpretable(i.ecg.measurements, i.ecg.statements)) && <p className="hidden px-[var(--card-pad)] py-2 text-[0.7rem] text-muted-foreground md:block">* Wide QRS or paced rhythm: QTc shown but not interpretable, and not used for triage.</p>}
          </div>
        </Card>

        <div className="min-w-0 space-y-4">
          <Card>
            <CardHeader title="Holter recordings" description="Long recordings analysed beat by beat" icon={<Activity />} actions={<Button size="xs" variant="ghost" asChild><Link to="/holter">All</Link></Button>} />
            <div className="card-pad space-y-2">
              {catalog.holters.map((h) => {
                const p = catalog.patients.find((x) => x.id === h.patient_id)!;
                return (
                  <Link key={h.id} to={`/holter/${h.id}`} className="flex items-center gap-3 rounded-xl border bg-card/70 p-2.5 transition-colors hover:border-primary/40">
                    <div className="flex size-9 items-center justify-center rounded-lg bg-primary-soft text-primary-soft-foreground"><Waves className="size-4" /></div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{p.name}</div>
                      <div className="truncate text-[0.72rem] text-muted-foreground">{h.findings[0]?.replace(/ \(.*\)/, "")}</div>
                    </div>
                    <span className="text-[0.72rem] text-muted-foreground num">{Math.round(h.duration_s / 60)} min</span>
                  </Link>
                );
              })}
            </div>
          </Card>
          <Card>
            <CardHeader title="AI engine" description="On-premise · this hospital's server" icon={<BrainCircuit />} />
            <div className="card-pad space-y-2 text-[0.8rem]">
              <div className="flex items-center gap-2"><span className="size-2 rounded-full bg-success" /> Online · all 4 models verified (SHA-256)</div>
              {Object.entries(catalog.engine.models).map(([role, m]) => (
                <div key={role} className="flex justify-between gap-2"><span className="capitalize text-muted-foreground">{role}</span><span className="font-mono text-[0.72rem]">{m.model}</span></div>
              ))}
              <div className="flex items-center gap-1.5 pt-1 text-[0.72rem] text-muted-foreground"><ShieldCheck className="size-3.5" /> {catalog.engine.intended_use}</div>
              <Button size="xs" variant="link" asChild><Link to="/ai">How the AI was tested <ArrowRight className="size-3" /></Link></Button>
            </div>
          </Card>
          <Card className="p-4 text-[0.78rem] text-muted-foreground">
            <div className="mb-1 flex items-center gap-1.5 font-semibold text-foreground"><Clock3 className="size-4" /> How triage works</div>
            Critical: complete heart block, AF/flutter ≥ 120 bpm, QTc ≥ 500 ms or rate &lt; 40 / ≥ 150. Urgent: infarction pattern, AF/flutter, long QT, WPW, LBBB, 2nd-degree block, SVT. It orders the reading — it never replaces it.
          </Card>
        </div>
      </div>
    </div>
  );
}
