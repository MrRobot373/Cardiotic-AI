import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileUp, Loader2, Monitor, Plug, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router";
import { useDemo } from "@/app/demo-store";
import { Badge, Button, Card, CardHeader, Field, Input, PageHeader, Select } from "@/components/ui";
import { FeedStatusList, useFeeds } from "@/features/settings/ServerSettings";
import { api, ApiError, serverMode } from "@/lib/server";
import { useCatalog } from "@/data/api";
import { statementName } from "@/data/clinical";
import { cn } from "@/lib/utils";

const FORMATS = ["DICOM waveform (12-lead ECG IOD)", "HL7 aECG (FDA XML)", "SCP-ECG (EN 1064)", "GE MUSE XML", "Philips PageWriter XML", "Schiller SEMA XML", "EDF / CSV"];
const STEPS = ["Read the file and its leads", "Match the patient (HIS / ADT)", "Signal quality, per lead", "Beats and median beat", "Intervals and axis", "Diagnostic statements"];
const DEVICES = [
  { name: "ECG room 1 · Schiller AT-102", via: "SEMA XML over the network share", last: "2 min ago", ok: true },
  { name: "ECG room 2 · GE MAC 2000", via: "MUSE XML", last: "11 min ago", ok: true },
  { name: "Emergency · Philips PageWriter TC50", via: "DICOM C-STORE", last: "1 h ago", ok: true },
  { name: "Ward 4B · BPL Cardiart 9108", via: "PDF only (image) — needs the digitiser", last: "yesterday", ok: false },
];

function StaticUpload() {
  const { data: c } = useCatalog();
  const { log } = useDemo();
  const [sample, setSample] = useState<string>("");
  const [file, setFile] = useState<string | null>(null);
  const [queued, setQueued] = useState(false);
  const [step, setStep] = useState(-1);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const ecg = c?.ecgs.find((e) => e.id === (sample || c?.ecgs[c.ecgs.length - 1]?.id));
  const patient = c?.patients.find((p) => p.id === ecg?.patient_id);
  /** A file from disk is handed to the engine's intake queue; a recording from a machine inbox is analysed straight away. */
  const receive = (name: string) => {
    setFile(name);
    setStep(-1);
    setQueued(true);
    log("Uploaded ECG", name);
  };
  const run = (name: string) => {
    setFile(name);
    setQueued(false);
    setStep(0);
    log("Uploaded ECG", name);
    STEPS.forEach((_, i) => setTimeout(() => setStep(i + 1), 350 * (i + 1)));
  };
  const done = step >= STEPS.length;
  return (
    <div className="animate-fade-in">
      <PageHeader title="Upload ECG" description="ECG machines normally send recordings to Cardiotic AI automatically. Upload is for the odd file from a USB stick, another hospital or a referral." />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="space-y-4">
          <Card>
            <div className="card-pad">
              <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
                onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) receive(f.name); }}
                className={cn("flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors", over ? "border-primary bg-primary-soft/40" : "border-border bg-subtle/60")}>
                <UploadCloud className="size-10 text-primary" />
                <div className="mt-3 text-base font-semibold">Drop an ECG file here</div>
                <div className="mt-1 text-sm text-muted-foreground">or</div>
                <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
                  <Button variant="strong" onClick={() => input.current?.click()}><FileUp /> Choose file</Button>
                  <input ref={input} type="file" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) receive(f.name); }} />
                </div>
                <div className="mt-5 flex max-w-xl flex-wrap justify-center gap-1.5">{FORMATS.map((f) => <Badge key={f} tone="outline">{f}</Badge>)}</div>
              </div>
              <div className="mt-4 flex flex-col gap-2 rounded-xl bg-subtle p-3 text-[0.8rem] sm:flex-row sm:items-center">
                <span className="text-muted-foreground">Or import a recording waiting in an ECG machine's inbox</span>
                <div className="flex items-center gap-2 sm:ml-auto">
                  <Select size="sm" className="w-64" value={sample || ecg?.id} onValueChange={setSample}
                    options={(c?.ecgs ?? []).map((e) => ({ value: e.id, label: `${c!.patients.find((p) => p.id === e.patient_id)?.name} · ${e.statements.filter((s) => !s.statement.startsWith("SUPER_"))[0] ? statementName(e.statements.filter((s) => !s.statement.startsWith("SUPER_"))[0].statement) : "ECG"}` }))} />
                  <Button size="sm" variant="secondary" onClick={() => run(`ECG_${ecg?.id}.xml`)}>Import</Button>
                </div>
              </div>
            </div>
          </Card>
          {queued && file && (
            <Card className="animate-slide-up">
              <CardHeader title={file} description="Received · queued for analysis on this hospital's server" icon={<FileUp />} />
              <div className="card-pad text-[0.82rem] text-muted-foreground">The file is checked for format and patient identity, then analysed. It appears in the worklist with its AI triage as soon as the engine has read it.
                <Button className="mt-3 flex" size="sm" variant="secondary" asChild><Link to="/">Go to worklist</Link></Button>
              </div>
            </Card>
          )}
          {step >= 0 && ecg && patient && (
            <Card className="animate-slide-up">
              <CardHeader title={file ?? ""} description={done ? "Analysed — ready for reading" : "Analysing on this hospital's server…"} icon={<FileUp />} />
              <div className="card-pad space-y-2">
                {STEPS.map((s, i) => (
                  <div key={s} className="flex items-center gap-2.5 text-sm">
                    {step > i ? <CheckCircle2 className="size-4 text-success" /> : step === i ? <Loader2 className="size-4 animate-spin text-primary" /> : <span className="size-4 rounded-full border" />}
                    <span className={cn(step > i ? "text-foreground" : "text-muted-foreground")}>{s}</span>
                    {i === 1 && step > 1 && <span className="ml-auto text-xs text-muted-foreground">{patient.name} · {patient.mrn}</span>}
                  </div>
                ))}
                {done && (
                  <div className="mt-3 rounded-xl border bg-card/70 p-3">
                    <div className="flex flex-wrap gap-1">{ecg.statements.filter((s) => !s.statement.startsWith("SUPER_")).map((s) => <Badge key={s.statement}>{statementName(s.statement)}</Badge>)}</div>
                    <div className="mt-2 text-[0.78rem] text-muted-foreground">Engine time for this ECG: about 30 ms. It is now in the worklist with its AI triage.</div>
                    <Button className="mt-3" variant="strong" asChild><Link to={`/ecg/${ecg.id}`}>Open for reading</Link></Button>
                  </div>
                )}
              </div>
            </Card>
          )}
        </div>
        <div className="space-y-4">
          <Card>
            <CardHeader title="Connected ECG machines" description="Recordings arrive here without anyone uploading" icon={<Plug />} />
            <div className="card-pad space-y-2">
              {DEVICES.map((d) => (
                <div key={d.name} className="flex items-start gap-3 rounded-xl border bg-card/70 p-3">
                  <Monitor className="mt-0.5 size-4 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{d.name}</div>
                    <div className="text-[0.75rem] text-muted-foreground">{d.via} · last ECG {d.last}</div>
                  </div>
                  <Badge tone={d.ok ? "success" : "warning"}>{d.ok ? "Connected" : "Image only"}</Badge>
                </div>
              ))}
              <p className="text-[0.72rem] text-muted-foreground">Machines that export only PDF or paper images are read through the ECG image digitiser.</p>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}


interface Uploaded {
  id: string;
  patient_id: string;
  statements?: { statement: string }[];
  measurements?: { heart_rate_bpm?: number };
  duration_s?: number;
  source: { dataset: string };
}

const FORMAT_NAMES: Record<string, string> = { "dicom-ecg": "DICOM ECG waveform", "hl7-aecg": "HL7 aECG", "ge-muse-xml": "GE MUSE XML", "scp-ecg": "SCP-ECG", edf: "EDF", csv: "CSV" };

/** Upload to the Cardiotic server: the file is read, analysed and stored; nothing is faked. */
function ServerUpload() {
  const qc = useQueryClient();
  const { user } = useDemo();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [mrn, setMrn] = useState("");
  const [location, setLocation] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<{ name: string; rec?: Uploaded; error?: string }[]>([]);
  const allowed = user?.role === "technician" || user?.role === "cardiologist";
  const feeds = useFeeds();

  const send = async (files: FileList | File[]) => {
    for (const f of Array.from(files)) {
      setBusy(f.name);
      try {
        const rec = await api<Uploaded>("/upload", {
          method: "POST",
          body: await f.arrayBuffer(),
          headers: { "Content-Type": "application/octet-stream", "X-Filename": f.name, ...(mrn.trim() ? { "X-Patient-MRN": mrn.trim() } : {}), ...(location.trim() ? { "X-Location": location.trim() } : {}) },
        });
        setDone((d) => [{ name: f.name, rec }, ...d]);
        qc.invalidateQueries({ queryKey: ["catalog"] });
      } catch (e) {
        setDone((d) => [{ name: f.name, error: e instanceof ApiError ? e.message : "Could not reach the server" }, ...d]);
      }
    }
    setBusy(null);
  };

  return (
    <div className="animate-fade-in">
      <PageHeader title="Upload ECG" description="ECG machines normally send recordings to Cardiotic AI automatically. Upload is for the odd file from a USB stick, another hospital or a referral." />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="space-y-4">
          <Card>
            <div className="card-pad">
              {!allowed && <p className="mb-3 rounded-lg bg-warning-soft p-3 text-sm">Only technicians and cardiologists can upload ECGs.</p>}
              <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
                onDrop={(e) => { e.preventDefault(); setOver(false); if (allowed && e.dataTransfer.files.length) void send(e.dataTransfer.files); }}
                className={cn("flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors", over ? "border-primary bg-primary-soft/40" : "border-border bg-subtle/60")}>
                <UploadCloud className="size-10 text-primary" />
                <div className="mt-3 text-base font-semibold">Drop an ECG file here</div>
                <div className="mt-1 text-sm text-muted-foreground">or</div>
                <div className="mt-3">
                  <Button variant="strong" disabled={!allowed || !!busy} onClick={() => input.current?.click()}><FileUp /> Choose file</Button>
                  <input ref={input} type="file" multiple className="hidden" aria-label="ECG file" onChange={(e) => { if (e.target.files?.length) void send(e.target.files); e.target.value = ""; }} />
                </div>
                <div className="mt-5 flex max-w-xl flex-wrap justify-center gap-1.5">{["DICOM ECG waveform", "HL7 aECG (FDA XML, SierraECG)", "GE MUSE XML", "SCP-ECG (uncompressed)", "EDF / EDF+", "CSV"].map((f) => <Badge key={f} tone="outline">{f}</Badge>)}</div>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <Field label="Patient MRN" hint="Only used when the file carries no patient ID"><Input value={mrn} onChange={(e) => setMrn(e.target.value)} placeholder="e.g. UH-20400" /></Field>
                <Field label="Location"><Input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="e.g. ECG room 1" /></Field>
              </div>
            </div>
          </Card>
          {busy && <Card><div className="card-pad flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin text-primary" /> Reading and analysing {busy}…</div></Card>}
          {done.map((d, i) => (
            <Card key={i} className="animate-slide-up">
              <CardHeader title={d.name} description={d.error ? "Not accepted" : d.rec?.id.startsWith("H") ? "Analysed — Holter recording" : "Analysed — ready for reading"} icon={d.error ? <AlertTriangle /> : <CheckCircle2 />} />
              <div className="card-pad space-y-2">
                {d.error && <p className="text-sm text-danger-foreground" role="alert">{d.error}</p>}
                {d.rec && (
                  <>
                    <div className="flex flex-wrap gap-1">
                      {(d.rec.statements ?? []).filter((s) => !s.statement.startsWith("SUPER_")).map((s) => <Badge key={s.statement}>{statementName(s.statement)}</Badge>)}
                    </div>
                    <div className="text-[0.78rem] text-muted-foreground">Read as {FORMAT_NAMES[d.rec.source.dataset] ?? d.rec.source.dataset}. It is now in the {d.rec.id.startsWith("H") ? "Holter list" : "worklist with its AI triage"}.</div>
                    <Button variant="strong" asChild><Link to={d.rec.id.startsWith("H") ? `/holter/${d.rec.id}` : `/ecg/${d.rec.id}`}>Open for reading</Link></Button>
                  </>
                )}
              </div>
            </Card>
          ))}
        </div>
        <div className="space-y-4">
        <Card>
          <CardHeader title="Connected ECG machines" description="Recordings arrive here without anyone uploading" icon={<Monitor />} />
          <div className="card-pad"><FeedStatusList feeds={feeds.data} /></div>
        </Card>
        <Card>
          <CardHeader title="Supported files" description="The format is recognised from the content" icon={<Plug />} />
          <div className="card-pad space-y-2 text-[0.8rem] text-muted-foreground">
            <p>12 leads (or I, II and V1–V6) are read as an ECG; a single lead as a Holter recording. A file without a patient ID is kept under “Unidentified patient” until it is matched.</p>
            <p>Not read yet: PDF and photographs of paper ECGs, Huffman-compressed SCP-ECG, Philips PageWriter XML. Export those from the machine as DICOM or HL7 aECG.</p>
          </div>
        </Card>
        </div>
      </div>
    </div>
  );
}

export default function UploadPage() {
  return serverMode ? <ServerUpload /> : <StaticUpload />;
}
