import {
  ArrowLeftRight, BrainCircuit, Check, ChevronLeft, ChevronRight, Cpu, Eye, FileText, HeartPulse, Info, Pencil, Plus, Printer,
  Ruler, Send, ShieldCheck, TriangleAlert, Undo2, X,
} from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { canSign, useDemo, type Review } from "@/app/demo-store";
import { ConfidenceBadge, PriorityBadge, ProbabilityBar, StatusBadge } from "@/components/clinical/badges";
import { PatientHeader } from "@/components/clinical/PatientHeader";
import { Ecg12View, type Layout } from "@/components/ecg/Ecg12View";
import { MedianBeats, type Calipers } from "@/components/ecg/MedianBeats";
import {
  Badge, Button, Card, CardHeader, Dialog, DialogContent, EmptyState, Popover, PopoverContent, PopoverTrigger, Segmented, Skeleton, Textarea, Tooltip,
} from "@/components/ui";
import { useEcgSignals } from "@/data/api";
import { axisLabel, isGroup, qtcInterpretable, rangeFlag, statementName } from "@/data/clinical";
import { byPriorityThenTime, useWorkItems, type WorkItem } from "@/data/derived";
import { leadsFor } from "@/data/leads";
import type { EcgDetail, Measurements, Statement } from "@/data/types";
import { cn, fmtDateTime } from "@/lib/utils";


/** Measurements after the reader's caliper edits (edits win; QTc recomputed from the edited QT). */
export function effectiveMeasurements(m: Measurements, review: Review): Measurements & { edited: Set<string> } {
  const out: Measurements & { edited: Set<string> } = { ...m, edited: new Set() };
  for (const [k, v] of Object.entries(review.edits)) {
    if (k.startsWith("cal.")) continue;
    (out as unknown as Record<string, number | null>)[k] = v;
    out.edited.add(k);
  }
  if (out.edited.has("qt_ms") && out.qt_ms && m.rr_ms) {
    out.qtc_bazett_ms = out.qt_ms / Math.sqrt(m.rr_ms / 1000);
    out.edited.add("qtc_bazett_ms");
  }
  return out;
}

export function finalStatements(ai: Statement[], review: Review): string[] {
  return [...ai.filter((s) => !isGroup(s.statement) && review.decisions[s.statement] !== "rejected").map((s) => s.statement), ...review.added];
}

function MeasureTile({ label, value, unit, sub, flag, edited }: { label: string; value: string; unit?: string; sub?: string; flag?: "low" | "high" | null; edited?: boolean }) {
  return (
    <div className={cn("rounded-xl border bg-card/70 p-3", flag && "border-warning/40 bg-warning-soft/40")}>
      <div className="flex items-center justify-between gap-1 text-[0.72rem] text-muted-foreground">
        <span>{label}</span>
        {edited && <Badge tone="info" className="px-1.5 text-[0.6rem]">edited</Badge>}
        {flag && !edited && <Badge tone="warning" className="px-1.5 text-[0.6rem]">{flag}</Badge>}
      </div>
      <div className="mt-0.5 text-[1.3rem] font-semibold tracking-tight num">{value}{unit && <span className="ml-1 text-[0.75rem] font-normal text-muted-foreground">{unit}</span>}</div>
      {sub && <div className="text-[0.7rem] text-muted-foreground">{sub}</div>}
    </div>
  );
}

function fmt(v: number | null | undefined, d = 0) {
  return v === null || v === undefined ? "—" : v.toFixed(d);
}

function Analysis({ item, detail, review }: { item: WorkItem; detail: EcgDetail; review: Review }) {
  const r = detail.analysis.result;
  const m = effectiveMeasurements(r.measurements, review);
  const sex = item.patient.sex;
  const q = r.lead_quality;
  const good = Object.values(q).filter((v) => v === "good").length;
  const bad = Object.entries(q).filter(([, v]) => v !== "good");
  if (!r.measurements.ok) {
    return (
      <Card>
        <CardHeader title="ECG analysis" icon={<Ruler />} />
        <div className="card-pad"><div className="rounded-lg bg-warning-soft p-3 text-sm text-warning-foreground">Measurements withheld: {String((r.measurements as { reason?: string }).reason ?? "signal not analysable")}. Repeat the ECG.</div></div>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader title="ECG analysis" description={`Median of ${r.measurements.beats_in_median ?? "?"} beats · ${r.measurements.beats_detected ?? "?"} detected`} icon={<Ruler />}
        actions={<Badge tone="outline">Draft · verify before acting</Badge>} />
      <div className="card-pad grid grid-cols-2 gap-2">
        <MeasureTile label="Heart rate" value={fmt(m.heart_rate_bpm)} unit="bpm" sub={r.measurements.rr_irregular ? "Irregular RR" : "Regular"} flag={rangeFlag("heart_rate_bpm", m.heart_rate_bpm)} edited={m.edited.has("heart_rate_bpm")} />
        <MeasureTile label="PR interval" value={m.pr_ms ? fmt(m.pr_ms) : "Not measured"} unit={m.pr_ms ? "ms" : undefined} sub={m.pr_ms ? undefined : "No consistent P waves"} flag={rangeFlag("pr_ms", m.pr_ms)} edited={m.edited.has("pr_ms")} />
        <MeasureTile label="QRS duration" value={fmt(m.qrs_ms)} unit="ms" flag={rangeFlag("qrs_ms", m.qrs_ms)} edited={m.edited.has("qrs_ms")} />
        <MeasureTile label="QT / QTc (Bazett)" value={`${fmt(m.qt_ms)} / ${fmt(m.qtc_bazett_ms)}`} unit="ms" sub={!qtcInterpretable(m, r.statements) ? "Wide QRS / paced: QTc not interpretable" : r.measurements.qtc_fridericia_ms ? `Fridericia ${fmt(r.measurements.qtc_fridericia_ms)}` : undefined}
          flag={qtcInterpretable(m, r.statements) ? rangeFlag("qtc_bazett_ms", m.qtc_bazett_ms, sex) : null} edited={m.edited.has("qt_ms")} />
        <MeasureTile label="Frontal QRS axis" value={`${m.qrs_axis_deg! > 0 ? "+" : ""}${fmt(m.qrs_axis_deg)}°`} sub={axisLabel(m.qrs_axis_deg)} flag={rangeFlag("qrs_axis_deg", m.qrs_axis_deg)} />
        <MeasureTile label="Signal quality" value={`${good} / 12`} unit="leads good" sub={bad.length ? bad.map(([l, v]) => `${l === "AVR" ? "aVR" : l === "AVL" ? "aVL" : l === "AVF" ? "aVF" : l} ${v}`).join(", ") : "All leads good"} flag={bad.some(([, v]) => v === "unusable") ? "low" : null} />
      </div>
      {(r.notes.length > 0 || detail.analysis.input_notes.length > 0) && (
        <div className="mx-[var(--card-pad)] mb-[var(--card-pad)] space-y-1 rounded-lg bg-subtle p-3 text-[0.78rem] text-muted-foreground">
          {[...r.notes, ...detail.analysis.input_notes].map((n) => <div key={n} className="flex gap-1.5"><Info className="mt-0.5 size-3.5 shrink-0" />{n}</div>)}
        </div>
      )}
    </Card>
  );
}

function FindingRow({ s, desc, decision, onDecide, onShow, showing }: {
  s: Statement; desc: Record<string, string>; decision?: "accepted" | "rejected"; onDecide: (d: "accepted" | "rejected" | null) => void; onShow: () => void; showing: boolean;
}) {
  return (
    <div className={cn("rounded-xl border bg-card/80 p-3 transition-colors", decision === "accepted" && "border-success/40 bg-success-soft/30", decision === "rejected" && "opacity-60")}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className={cn("text-[0.9rem] font-semibold", decision === "rejected" && "line-through")}>{statementName(s.statement, desc)}</div>
          <div className="text-[0.7rem] text-muted-foreground">SCP-ECG {s.statement} · AI probability {Math.round(s.probability * 100)}%</div>
        </div>
        <ConfidenceBadge level={s.confidence} />
      </div>
      <ProbabilityBar p={s.probability} threshold={s.threshold} className="mt-2" />
      <div className="mt-2.5 flex flex-wrap items-center gap-1">
        {decision ? (
          <>
            <Badge tone={decision === "accepted" ? "success" : "neutral"}>{decision === "accepted" ? <Check /> : <X />}{decision === "accepted" ? "Accepted" : "Rejected"}</Badge>
            <Button size="xs" variant="ghost" onClick={() => onDecide(null)}><Undo2 /> Undo</Button>
          </>
        ) : (
          <>
            <Button size="xs" variant="secondary" onClick={() => onDecide("accepted")}><Check /> Accept</Button>
            <Button size="xs" variant="ghost" onClick={() => onDecide("rejected")}><X /> Reject</Button>
          </>
        )}
        {leadsFor(s.statement).length > 0 && (
          <Button size="xs" variant="link" className="ml-auto" onClick={onShow}><Eye className="size-3.5" /> {showing ? "Hide" : "Show on ECG"}</Button>
        )}
      </div>
    </div>
  );
}

const ADDABLE = ["NORM", "SR", "SBRAD", "STACH", "AFIB", "AFLT", "1AVB", "2AVB", "3AVB", "CLBBB", "CRBBB", "IRBBB", "LAFB", "LVH", "IMI", "ASMI", "AMI", "ALMI", "ISC_", "NST_", "STD_", "STE_", "LNGQT", "PVC", "PAC", "WPW", "PACE", "LVOLT"];

function Findings({ item, detail, review, onShow, showing }: { item: WorkItem; detail: EcgDetail; review: Review; onShow: (code: string | null) => void; showing: string | null }) {
  const { updateReview, user } = useDemo();
  const { catalog } = useWorkItems();
  const desc = catalog?.statement_descriptions ?? {};
  const ai = detail.analysis.result.statements;
  const findings = ai.filter((s) => !isGroup(s.statement));
  const groups = ai.filter((s) => isGroup(s.statement));
  const decided = findings.filter((s) => review.decisions[s.statement]).length;
  const decide = (code: string, d: "accepted" | "rejected" | null) =>
    updateReview(item.ecg.id, (r) => {
      const decisions = { ...r.decisions };
      if (d) decisions[code] = d; else delete decisions[code];
      return { decisions, status: r.status === "new" ? "in_review" : r.status };
    }, d ? `${d === "accepted" ? "Accepted" : "Rejected"} AI finding ${code}` : undefined);
  const signed = review.status === "signed";
  return (
    <Card>
      <CardHeader title="AI findings" description={signed ? "Signed — read only" : "Accept or reject each one before signing"} icon={<BrainCircuit />}
        actions={<Tooltip content={`${detail.analysis.engine.models.ecg12.model} · ${detail.analysis.engine.models.ecg12.sha256.slice(0, 12)}`}><span><Badge tone="primary"><Cpu /> {detail.analysis.engine.models.ecg12.model.replace("ecg12_net_", "ecg12 ")}</Badge></span></Tooltip>} />
      <div className="card-pad space-y-2">
        {groups.length > 0 && (
          <div className="flex flex-wrap gap-1 pb-1">
            {groups.map((g) => <Badge key={g.statement} tone="outline">{statementName(g.statement)} · {Math.round(g.probability * 100)}%</Badge>)}
          </div>
        )}
        {findings.length === 0 && <EmptyState compact title="No AI findings above threshold" description="The reader can add findings below." />}
        <fieldset disabled={signed} className="space-y-2">
          {findings.map((s) => (
            <FindingRow key={s.statement} s={s} desc={desc} decision={review.decisions[s.statement]} onDecide={(d) => decide(s.statement, d)}
              onShow={() => onShow(showing === s.statement ? null : s.statement)} showing={showing === s.statement} />
          ))}
        </fieldset>
        {review.added.map((c) => (
          <div key={c} className="flex items-center justify-between gap-2 rounded-xl border border-dashed bg-card/60 p-3">
            <div>
              <div className="text-[0.9rem] font-semibold">{statementName(c, desc)}</div>
              <div className="text-[0.7rem] text-muted-foreground">Added by {user?.name}</div>
            </div>
            {!signed && <Button size="icon-xs" variant="ghost" aria-label="Remove" onClick={() => updateReview(item.ecg.id, (r) => ({ added: r.added.filter((x) => x !== c) }), `Removed added finding ${c}`)}><X /></Button>}
          </div>
        ))}
        {!signed && (
          <Popover>
            <PopoverTrigger asChild><Button size="sm" variant="ghost" className="w-full border border-dashed"><Plus /> Add finding</Button></PopoverTrigger>
            <PopoverContent className="max-h-80 w-72 overflow-y-auto p-1">
              {ADDABLE.filter((c) => !finalStatements(ai, review).includes(c)).map((c) => (
                <button key={c} className="block w-full rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-muted"
                  onClick={() => updateReview(item.ecg.id, (r) => ({ added: [...r.added, c], status: r.status === "new" ? "in_review" : r.status }), `Added finding ${c}`)}>
                  {statementName(c, desc)}
                </button>
              ))}
            </PopoverContent>
          </Popover>
        )}
        <div className="flex items-center justify-between pt-1 text-xs text-muted-foreground">
          <span>{decided} of {findings.length} AI findings reviewed</span>
          {!signed && findings.length > 0 && decided < findings.length && (
            <Button size="xs" variant="link" onClick={() => updateReview(item.ecg.id, (r) => ({ decisions: Object.fromEntries(findings.map((s) => [s.statement, r.decisions[s.statement] ?? "accepted"])), status: "in_review" }), "Accepted remaining AI findings")}>Accept remaining</Button>
          )}
        </div>
      </div>
    </Card>
  );
}

function Reference({ item }: { item: WorkItem }) {
  const { catalog } = useWorkItems();
  const desc = catalog?.statement_descriptions ?? {};
  const ai = new Set(item.ecg.statements.map((s) => s.statement));
  return (
    <Card>
      <CardHeader title="Validation reference" description={`Labels from the ${item.ecg.source.dataset} cardiologists`} icon={<ShieldCheck />} />
      <div className="card-pad flex flex-wrap gap-1.5">
        {item.ecg.reference_statements.map((c) => (
          <Badge key={c} tone={ai.has(c) ? "success" : "warning"}>{ai.has(c) ? <Check /> : <TriangleAlert />}{statementName(c, desc)}</Badge>
        ))}
        <p className="w-full pt-1 text-[0.7rem] text-muted-foreground">Green: the AI also said it · amber: the AI did not. {item.ecg.source.dataset} record {String(item.ecg.source.record)} · {item.ecg.source.role}.</p>
      </div>
    </Card>
  );
}

function Compare({ item }: { item: WorkItem }) {
  const prev = item.previous;
  if (!prev) return null;
  const rows: [string, (m: Measurements) => number | null | undefined, number][] = [
    ["Heart rate", (m) => m.heart_rate_bpm, 10], ["PR", (m) => m.pr_ms, 20], ["QRS", (m) => m.qrs_ms, 20], ["QTc (Bazett)", (m) => m.qtc_bazett_ms, 30], ["QRS axis", (m) => m.qrs_axis_deg, 30],
  ];
  const names = (e: typeof prev) => new Set(e.statements.filter((s) => !isGroup(s.statement)).map((s) => s.statement));
  const a = names(prev), b = names(item.ecg);
  const newF = [...b].filter((x) => !a.has(x)), gone = [...a].filter((x) => !b.has(x));
  return (
    <Card>
      <CardHeader title="Compared with previous ECG" description={fmtDateTime(prev.recorded_at)} icon={<ArrowLeftRight />}
        actions={<Button size="xs" variant="ghost" asChild><Link to={`/ecg/${prev.id}`}>Open</Link></Button>} />
      <div className="card-pad">
        <table className="w-full text-[0.82rem]">
          <thead><tr className="text-label"><th className="pb-1.5 text-left font-semibold">&nbsp;</th><th className="pb-1.5 text-right font-semibold">Before</th><th className="pb-1.5 text-right font-semibold">Now</th><th className="pb-1.5 text-right font-semibold">Change</th></tr></thead>
          <tbody>
            {rows.map(([label, get, tol]) => {
              const x = get(prev.measurements), y = get(item.ecg.measurements);
              const d = x != null && y != null ? y - x : null;
              return (
                <tr key={label} className="border-t">
                  <td className="py-1.5">{label}</td>
                  <td className="py-1.5 text-right num">{fmt(x)}</td>
                  <td className="py-1.5 text-right font-medium num">{fmt(y)}</td>
                  <td className="py-1.5 text-right">{d === null ? "—" : Math.abs(d) < tol ? <span className="text-muted-foreground">Unchanged</span> : <Badge tone="info">{d > 0 ? "+" : ""}{Math.round(d)}</Badge>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {(newF.length > 0 || gone.length > 0) && (
          <div className="mt-3 space-y-1 text-[0.78rem]">
            {newF.length > 0 && <div><span className="font-semibold text-warning-foreground">New: </span>{newF.map((c) => statementName(c)).join(", ")}</div>}
            {gone.length > 0 && <div><span className="font-semibold text-muted-foreground">No longer: </span>{gone.map((c) => statementName(c)).join(", ")}</div>}
          </div>
        )}
      </div>
    </Card>
  );
}

function SignPanel({ item, detail, review }: { item: WorkItem; detail: EcgDetail; review: Review }) {
  const { user, updateReview } = useDemo();
  const navigate = useNavigate();
  const [note, setNote] = useState(review.note);
  const findings = detail.analysis.result.statements.filter((s) => !isGroup(s.statement));
  const pending = findings.filter((s) => !review.decisions[s.statement]).length;
  if (review.status === "signed") {
    return (
      <Card className="border-success/30">
        <div className="card-pad space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-success-foreground"><ShieldCheck className="size-4" /> Signed by {review.signedBy}</div>
          <div className="text-xs text-muted-foreground">{fmtDateTime(review.signedAt)} · report sent to HIS (HL7 ORU^R01) · ordering doctor {item.ecg.ordered_by} notified</div>
          {review.note && <p className="rounded-lg bg-subtle p-2.5 text-[0.82rem]">{review.note}</p>}
          <div className="flex gap-2">
            <Button size="sm" variant="strong" asChild><Link to={`/ecg/${item.ecg.id}/report`}><FileText /> View report</Link></Button>
            {canSign(user) && <Button size="sm" variant="ghost" onClick={() => updateReview(item.ecg.id, { status: "in_review", signedAt: undefined, signedBy: undefined }, "Re-opened signed report (amendment)")}><Pencil /> Amend</Button>}
          </div>
        </div>
      </Card>
    );
  }
  const sign = () => {
    updateReview(item.ecg.id, { status: "signed", note, signedBy: user!.name, signedAt: new Date().toISOString() }, "Signed ECG report");
    toast.success("Report signed and sent", { description: "HL7 ORU^R01 to the HIS · PDF stored · ordering doctor notified" });
  };
  return (
    <Card>
      <div className="card-pad space-y-3">
        <Textarea value={note} onChange={(e) => setNote(e.target.value)} onBlur={() => note !== review.note && updateReview(item.ecg.id, { note })} placeholder="Interpretation note — kept with the ECG and printed on the report" />
        {canSign(user) ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="strong" className="flex-1" disabled={pending > 0} onClick={sign}><ShieldCheck /> Sign & send report</Button>
            <Button variant="secondary" onClick={() => { updateReview(item.ecg.id, { status: "repeat", note }, "Requested repeat ECG"); toast("Repeat ECG requested", { description: `${item.ecg.location} notified` }); navigate("/"); }}>Request repeat</Button>
          </div>
        ) : (
          <Button variant="strong" className="w-full" onClick={() => { updateReview(item.ecg.id, { status: "in_review", note }, "Sent ECG for reading"); toast.success("Sent to the cardiologist's worklist"); }}><Send /> Send for reading</Button>
        )}
        <p className="text-[0.72rem] text-muted-foreground">
          {canSign(user) ? (pending > 0 ? `Decide on ${pending} more AI finding${pending > 1 ? "s" : ""} to sign.` : "Nothing leaves Cardiotic AI before sign-off.") : "Only a cardiologist can sign. Switch user from the account menu."}
        </p>
      </div>
    </Card>
  );
}

function EcgPanel({ item, detail, signals, review, highlight }: {
  item: WorkItem; detail: EcgDetail; signals: { leads: Record<string, Float32Array>; median: Record<string, Float32Array> }; review: Review; highlight: string | null;
}) {
  const { updateReview } = useDemo();
  const [view, setView] = useState<"full" | "median">("full");
  const [layout, setLayout] = useState<Layout>("3x4");
  const [speed, setSpeed] = useState<"25" | "50">("25");
  const [gain, setGain] = useState<"5" | "10" | "20">("10");
  const [caliper, setCaliper] = useState(false);
  const [showBeats, setShowBeats] = useState(true);
  const [editCal, setEditCal] = useState(false);
  const r = detail.analysis.result;
  const f = r.measurements.fiducials;
  const toMs = (v: number | null | undefined) => (v === null || v === undefined || !f ? null : Math.round(((v - f.r) / f.fs) * 1000));
  const ai: Calipers | null = f ? { pOn: toMs(f.p_on), qrsOn: toMs(f.qrs_on)!, qrsOff: toMs(f.qrs_off)!, tEnd: toMs(f.t_end) } : null;
  const cal: Calipers | null = ai ? {
    pOn: (review.edits["cal.pOn"] as number | null | undefined) ?? ai.pOn, qrsOn: (review.edits["cal.qrsOn"] as number | undefined) ?? ai.qrsOn,
    qrsOff: (review.edits["cal.qrsOff"] as number | undefined) ?? ai.qrsOff, tEnd: (review.edits["cal.tEnd"] as number | null | undefined) ?? ai.tEnd,
  } : null;
  const beats = useMemo(() => (detail.median?.r_peaks_s ?? []).map((t, i) => ({ t, label: detail.median!.in_median[i] ? "N" : "•", tone: detail.median!.in_median[i] ? "normal" as const : "ectopic" as const })), [detail.median]);
  const onCal = (c: Calipers) => {
    const edits: Record<string, number | null> = { "cal.pOn": c.pOn, "cal.qrsOn": c.qrsOn, "cal.qrsOff": c.qrsOff, "cal.tEnd": c.tEnd, qrs_ms: c.qrsOff - c.qrsOn };
    if (c.pOn !== null) edits.pr_ms = c.qrsOn - c.pOn;
    if (c.tEnd !== null) edits.qt_ms = c.tEnd - c.qrsOn;
    updateReview(item.ecg.id, (rv) => ({ edits: { ...rv.edits, ...edits }, status: rv.status === "new" ? "in_review" : rv.status }));
  };
  const resetCal = () => updateReview(item.ecg.id, { edits: {} }, "Reset calipers to AI");
  const editedCal = Object.keys(review.edits).some((k) => k.startsWith("cal."));
  return (
    <Card className="min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-3 px-[var(--card-pad)] pt-[var(--card-pad)]">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-primary-soft text-primary-soft-foreground ring-1 ring-primary/10"><HeartPulse className="size-4" /></div>
          <div className="min-w-0">
            <h3 className="text-[0.95rem] font-semibold tracking-tight">ECG 12-lead — resting</h3>
            <p className="text-[0.8rem] text-muted-foreground">{fmtDateTime(item.ecg.recorded_at)} · {item.ecg.location} · ordered by {item.ecg.ordered_by}</p>
          </div>
        </div>
        <Segmented size="sm" value={view} onChange={setView} options={[{ value: "full", label: "Full ECG" }, { value: "median", label: "Median beats" }]} />
      </div>
      <div className="flex flex-wrap items-center gap-1.5 px-[var(--card-pad)] pt-3 text-[0.72rem]">
        {view === "full" ? (
          <>
            <Segmented size="sm" value={layout} onChange={setLayout} options={[{ value: "3x4", label: "3×4" }, { value: "6x2", label: "6×2" }, { value: "12x1", label: "12×1" }]} />
            <Segmented size="sm" value={speed} onChange={setSpeed} options={[{ value: "25", label: "25 mm/s" }, { value: "50", label: "50 mm/s" }]} />
            <Segmented size="sm" value={gain} onChange={setGain} options={[{ value: "5", label: "5" }, { value: "10", label: "10 mm/mV" }, { value: "20", label: "20" }]} />
            <div className="ml-auto flex gap-1">
              <Button size="xs" variant={showBeats ? "soft" : "ghost"} onClick={() => setShowBeats((v) => !v)}><HeartPulse /> Beats</Button>
              <Button size="xs" variant={caliper ? "soft" : "ghost"} onClick={() => setCaliper((v) => !v)}><Ruler /> Calipers</Button>
            </div>
          </>
        ) : (
          <>
            <span className="text-muted-foreground">Median of {detail.median?.n_beats ?? "?"} beats per lead · dashed lines are the AI's fiducial points (P onset, QRS onset/end, T end)</span>
            <div className="ml-auto flex gap-1">
              {editedCal && <Button size="xs" variant="ghost" onClick={resetCal}><Undo2 /> Reset to AI</Button>}
              <Button size="xs" variant={editCal ? "soft" : "ghost"} disabled={review.status === "signed"} onClick={() => setEditCal((v) => !v)}><Pencil /> {editCal ? "Done" : "Edit calipers"}</Button>
            </div>
          </>
        )}
      </div>
      <div className="card-pad">
        {view === "full" ? (
          <>
            <Ecg12View leads={signals.leads} fs={detail.fs} layout={layout} speed={Number(speed) as 25 | 50} gain={Number(gain) as 5 | 10 | 20}
              beats={showBeats ? beats : []} leadQuality={r.lead_quality} highlightLeads={highlight ? leadsFor(highlight) : []} caliper={caliper}
              header={{ left: `${item.patient.name.toUpperCase()} · ${item.patient.sex}/${item.patient.age ?? "?"}Y · ${item.patient.mrn}`, right: `${speed} mm/s · ${gain} mm/mV · 0.05–150 Hz · ${item.ecg.device}` }} />
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[0.72rem] text-muted-foreground">
              {caliper && <span className="font-medium text-primary">Drag across the ECG to measure; double-click to clear.</span>}
              {highlight && <span className="font-medium text-primary">Highlighted: leads that show {statementName(highlight)}.</span>}
              <span>Numbers between beats: RR interval in ms. Grey: lead rated unusable; amber: noisy.</span>
            </div>
          </>
        ) : detail.median && cal ? (
          <MedianBeats beats={signals.median} fs={detail.median.fs} r={detail.median.r} calipers={cal} edit={editCal} onChange={onCal} leadQuality={r.lead_quality} />
        ) : <EmptyState compact title="No median beat" description="Too few beats to build one." />}
      </div>
    </Card>
  );
}

function Neighbours({ id }: { id: string }) {
  const { items } = useWorkItems();
  const list = useMemo(() => [...items].sort(byPriorityThenTime), [items]);
  const i = list.findIndex((x) => x.ecg.id === id);
  const prev = list[i - 1], next = list[i + 1];
  return (
    <div className="flex items-center gap-1">
      <Tooltip content="Previous in worklist"><Button size="icon" variant="secondary" disabled={!prev} asChild={!!prev}>{prev ? <Link to={`/ecg/${prev.ecg.id}`} aria-label="Previous"><ChevronLeft /></Link> : <span><ChevronLeft /></span>}</Button></Tooltip>
      <span className="px-1 text-xs text-muted-foreground num">{i + 1} / {list.length}</span>
      <Tooltip content="Next in worklist"><Button size="icon" variant="secondary" disabled={!next} asChild={!!next}>{next ? <Link to={`/ecg/${next.ecg.id}`} aria-label="Next"><ChevronRight /></Link> : <span><ChevronRight /></span>}</Button></Tooltip>
    </div>
  );
}

export default function EcgReviewPage() {
  const { id } = useParams();
  const { site } = useDemo();
  const { items, isLoading } = useWorkItems();
  const { data: detail, signals, isLoading: loadingEcg, error } = useEcgSignals(id);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [infoOpen, setInfoOpen] = useState(false);
  const item = items.find((x) => x.ecg.id === id);
  if (isLoading || loadingEcg) return <div className="space-y-4"><Skeleton className="h-14 w-96" /><Skeleton className="h-[520px] w-full" /></div>;
  if (error || !item || !detail || !signals) return <EmptyState title="ECG not found" description={String(error ?? "")} action={<Button asChild><Link to="/">Back to worklist</Link></Button>} />;
  const rv = item.review;
  return (
    <div className="animate-fade-in">
      <PatientHeader patient={item.patient}
        chips={<><PriorityBadge priority={item.priority} /><StatusBadge status={rv.status} /><Badge tone="outline">{item.reason}</Badge></>}
        actions={<>
          <Neighbours id={item.ecg.id} />
          <Button variant="secondary" onClick={() => setInfoOpen(true)}><Info /> Recording</Button>
          <Button variant="secondary" asChild><Link to={`/patients/${item.patient.id}`}>Patient</Link></Button>
          <Button variant="strong" asChild><Link to={`/ecg/${item.ecg.id}/report`}><Printer /> Report</Link></Button>
        </>} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-w-0 space-y-4">
          <EcgPanel item={item} detail={detail} signals={signals} review={rv} highlight={highlight} />
          <div className={cn("grid gap-4", site.showReference && "lg:grid-cols-2")}>
            <Compare item={item} />
            {site.showReference && <Reference item={item} />}
          </div>
        </div>
        <div className="space-y-4">
          <Analysis item={item} detail={detail} review={rv} />
          <Findings item={item} detail={detail} review={rv} onShow={setHighlight} showing={highlight} />
          <SignPanel item={item} detail={detail} review={rv} />
        </div>
      </div>
      <Dialog open={infoOpen} onOpenChange={setInfoOpen}>
        <DialogContent title="Recording and analysis" icon={<Info />}>
          <dl className="grid grid-cols-[140px_1fr] gap-y-2 text-sm">
            <dt className="text-muted-foreground">Device</dt><dd>{item.ecg.device}</dd>
            {site.showReference && <>
              <dt className="text-muted-foreground">Source</dt><dd>{item.ecg.source.dataset} · record {String(item.ecg.source.record)} · {item.ecg.source.licence}</dd>
              <dt className="text-muted-foreground">Role</dt><dd>{item.ecg.source.role}</dd>
            </>}
            <dt className="text-muted-foreground">Engine</dt><dd>{detail.analysis.engine.engine} {detail.analysis.engine.version} · models {detail.analysis.engine.models_version}</dd>
            {Object.entries(detail.analysis.engine.models).map(([role, m]) => (
              <Fragment key={role}><dt className="capitalize text-muted-foreground">{role} model</dt><dd className="font-mono text-xs">{m.model} · {m.sha256.slice(0, 16)}…</dd></Fragment>
            ))}
            <dt className="text-muted-foreground">Processing</dt><dd>{detail.analysis.processing_ms} ms</dd>
          </dl>
        </DialogContent>
      </Dialog>
    </div>
  );
}
