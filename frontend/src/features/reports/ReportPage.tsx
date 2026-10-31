import { ArrowLeft, FileDown, Printer } from "lucide-react";
import { serverMode } from "@/lib/server";
import { Link, useParams } from "react-router";
import { useDemo } from "@/app/demo-store";

import { CardioticMark } from "@/components/layout/BrandMark";
import { Ecg12View } from "@/components/ecg/Ecg12View";
import { Button, Skeleton } from "@/components/ui";
import { useEcgSignals } from "@/data/api";
import { ageLabel, axisLabel, qtcInterpretable, sexLabel, statementName } from "@/data/clinical";
import { useWorkItems } from "@/data/derived";
import { effectiveMeasurements, finalStatements } from "@/features/review/EcgReviewPage";
import { fmtDateTime } from "@/lib/utils";

const f = (v: number | null | undefined) => (v === null || v === undefined ? "—" : Math.round(v).toString());

/** Printable report — what the HIS receives as PDF (with HL7 ORU / FHIR DiagnosticReport alongside). */
export default function ReportPage() {
  const { id } = useParams();
  const { site } = useDemo();
  const { items, catalog } = useWorkItems();
  const { data: detail, signals } = useEcgSignals(id);
  const item = items.find((x) => x.ecg.id === id);
  if (!item || !detail || !signals || !catalog) return <div className="mx-auto max-w-[900px] p-6"><Skeleton className="h-[900px]" /></div>;
  const rv = item.review;
  const r = detail.analysis.result;
  const m = effectiveMeasurements(r.measurements, rv);
  const signed = rv.status === "signed";
  const lines = finalStatements(r.statements, rv);
  const desc = catalog.statement_descriptions;
  return (
    <div className="min-h-screen bg-muted/50 py-6 print:bg-white print:py-0">
      <div className="no-print mx-auto mb-4 flex max-w-[900px] items-center gap-2 px-4">
        <Button variant="secondary" asChild><Link to={`/ecg/${item.ecg.id}`}><ArrowLeft /> Back to review</Link></Button>
        {serverMode && <Button variant="secondary" className="ml-auto" asChild><a href={`${import.meta.env.BASE_URL.replace(/\/$/, "")}/api/report/${item.ecg.id}.pdf`} target="_blank" rel="noreferrer"><FileDown /> PDF report</a></Button>}
        <Button variant="strong" className={serverMode ? "" : "ml-auto"} onClick={() => window.print()}><Printer /> Print</Button>
      </div>
      <article className="relative mx-auto max-w-[900px] bg-white px-10 py-8 text-[13px] text-slate-900 shadow-card print:max-w-none print:px-6 print:py-4 print:shadow-none">
        {!signed && <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[110px] font-bold tracking-widest text-slate-900/[0.05] [transform:rotate(-24deg)]">DRAFT</div>}
        <header className="flex items-start justify-between border-b border-slate-200 pb-4">
          <div className="flex items-center gap-3">
            <CardioticMark className="size-10" />
            <div>
              <div className="text-lg font-semibold">{site.siteName}</div>
              <div className="text-xs text-slate-500">12-lead ECG report · Cardiotic AI assisted</div>
            </div>
          </div>
          <div className="text-right text-xs text-slate-500">
            <div className="font-semibold text-slate-900">{signed ? "FINAL REPORT" : "DRAFT — NOT SIGNED"}</div>
            <div>Report {item.ecg.id} · printed {fmtDateTime(new Date())}</div>
          </div>
        </header>
        <section className="grid grid-cols-3 gap-4 border-b border-slate-200 py-3 text-xs">
          <div><div className="text-slate-500">Patient</div><div className="text-sm font-semibold">{item.patient.name}</div><div>{item.patient.mrn} · {ageLabel(item.patient.age, item.patient.age_90_plus)} · {sexLabel(item.patient.sex)}</div></div>
          <div><div className="text-slate-500">Recorded</div><div className="font-medium">{fmtDateTime(item.ecg.recorded_at)}</div><div>{item.ecg.location} · {item.ecg.device}</div></div>
          <div><div className="text-slate-500">Ordered by</div><div className="font-medium">{item.ecg.ordered_by}</div><div>25 mm/s · 10 mm/mV · 0.05–150 Hz</div></div>
        </section>
        <section className="grid grid-cols-6 gap-2 py-3 text-center">
          {[["Rate", f(m.heart_rate_bpm), "bpm"], ["PR", m.pr_ms ? f(m.pr_ms) : "—", "ms"], ["QRS", f(m.qrs_ms), "ms"], ["QT", f(m.qt_ms), "ms"],
            ["QTc (Bazett)", f(m.qtc_bazett_ms) + (qtcInterpretable(m, r.statements) ? "" : "*"), "ms"], ["QRS axis", f(m.qrs_axis_deg), "°"]].map(([k, v, u]) => (
            <div key={k} className="rounded-md border border-slate-200 py-2"><div className="text-[11px] text-slate-500">{k}</div><div className="text-base font-semibold">{v}<span className="ml-0.5 text-[11px] font-normal text-slate-500">{u}</span></div></div>
          ))}
        </section>
        <Ecg12View leads={signals.leads} fs={detail.fs} forceLight header={{ left: `${item.patient.name.toUpperCase()} · ${item.patient.mrn}`, right: fmtDateTime(item.ecg.recorded_at) }} />
        <section className="mt-4 grid grid-cols-[1fr_260px] gap-6">
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Interpretation</div>
            {lines.length ? <ol className="list-decimal space-y-0.5 pl-5 text-sm font-medium">{lines.map((c) => <li key={c}>{statementName(c, desc)}</li>)}</ol> : <p className="text-sm">No abnormality stated.</p>}
            <p className="mt-1 text-xs text-slate-500">{axisLabel(m.qrs_axis_deg)}.{!qtcInterpretable(m, r.statements) && " * QTc not interpretable with wide QRS / pacing."}{m.edited.size > 0 && " Intervals adjusted by the reader."}</p>
            {rv.note && <><div className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Comment</div><p className="text-sm">{rv.note}</p></>}
          </div>
          <div className="rounded-md border border-slate-200 p-3 text-xs">
            <div className="text-slate-500">{signed ? "Electronically signed by" : "Awaiting signature"}</div>
            <div className="mt-1 text-sm font-semibold">{signed ? rv.signedBy : "—"}</div>
            <div>{signed ? fmtDateTime(rv.signedAt) : "Not valid until signed by a cardiologist"}</div>
          </div>
        </section>
        <footer className="mt-6 border-t border-slate-200 pt-2 text-[10px] leading-relaxed text-slate-500">
          Pre-read by {detail.analysis.engine.engine} {detail.analysis.engine.version} (models {detail.analysis.engine.models_version}: {Object.values(detail.analysis.engine.models).map((x) => `${x.model} ${x.sha256.slice(0, 8)}`).join(", ")}); interpretation confirmed by the signing physician.
        </footer>
      </article>
    </div>
  );
}
