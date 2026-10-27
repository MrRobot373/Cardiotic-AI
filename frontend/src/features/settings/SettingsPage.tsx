import { Building2, Info, Palette, Plug, Users } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink, useParams } from "react-router";
import { toast } from "sonner";
import { useAppearance } from "@/app/appearance";
import { DEMO_USERS, useDemo } from "@/app/demo-store";
import { Avatar, Badge, Card, CardHeader, PageHeader, Segmented, SwitchRow } from "@/components/ui";
import { useCatalog } from "@/data/api";
import { ACCENT_PRESETS } from "@/lib/color";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { id: "site", label: "Site & AI operating points", icon: Building2 },
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "integrations", label: "Integrations", icon: Plug },
  { id: "users", label: "Users & roles", icon: Users },
  { id: "about", label: "About", icon: Info },
];

function Row({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 border-b py-4 last:border-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="max-w-md"><div className="text-sm font-medium">{label}</div>{hint && <div className="text-[0.78rem] text-muted-foreground">{hint}</div>}</div>
      <div>{children}</div>
    </div>
  );
}

function Site() {
  const { site, updateSite, user } = useDemo();
  const admin = user?.role === "admin" || user?.role === "cardiologist";
  return (
    <Card>
      <CardHeader title="Site & AI operating points" description="How sure the AI must be before it states a finding at this hospital" icon={<Building2 />} />
      <div className="px-[var(--card-pad)] pb-[var(--card-pad)]">
        <Row label="Operating point" hint="Sensitive: fewer missed findings, more to reject. Specific: fewer false findings, more chance of a miss. Chosen per site on its own validation ECGs.">
          <Segmented value={site.operatingPoint} onChange={(v) => { if (!admin) return toast.error("Only the cardiology lead or an administrator can change this"); updateSite({ operatingPoint: v }); toast.success("Saved for this site (demo: the shown AI output does not change)"); }}
            options={[{ value: "sensitive", label: "Sensitive" }, { value: "balanced", label: "Balanced" }, { value: "specific", label: "Specific" }]} />
        </Row>
        <SwitchRow label="Rate statements from measurements" description="Write sinus bradycardia / tachycardia by the heart-rate definition (< 60 / > 100 bpm) instead of the learned statement. Hospitals differ: PTB-XL cardiologists rarely wrote bradycardia for 55–59 bpm; Chapman's always did."
          checked={site.ratesFromMeasurements} onCheckedChange={(v) => updateSite({ ratesFromMeasurements: v })} />
        <SwitchRow label="Send signed reports to the HIS automatically" description="HL7 ORU^R01 with the PDF, as soon as a cardiologist signs." checked={site.autoSendHis} onCheckedChange={(v) => updateSite({ autoSendHis: v })} />
        <div className="mt-4 rounded-xl bg-subtle p-3 text-[0.78rem] text-muted-foreground">
          In the product, a change here creates a new configuration version: it is validated on the site's own ECGs, approved by the cardiology lead, recorded in the audit log and can be rolled back. It never changes the model itself.
        </div>
      </div>
    </Card>
  );
}

function Appearance() {
  const { appearance, update } = useAppearance();
  return (
    <Card>
      <CardHeader title="Appearance" description="Saved in this browser" icon={<Palette />} />
      <div className="px-[var(--card-pad)] pb-[var(--card-pad)]">
        <Row label="Theme"><Segmented value={appearance.theme} onChange={(v) => update({ theme: v })} options={[{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }, { value: "system", label: "System" }]} /></Row>
        <Row label="Accent colour">
          <div className="flex flex-wrap gap-1.5">
            {ACCENT_PRESETS.map((a) => (
              <button key={a.hex} title={a.name} onClick={() => update({ accent: a.hex })} className={cn("size-7 rounded-full ring-offset-2 ring-offset-background", appearance.accent === a.hex && "ring-2 ring-foreground")} style={{ background: a.hex }} />
            ))}
          </div>
        </Row>
        <Row label="ECG paper" hint="Pink is the classic paper colour; green and grey suit some reading rooms."><Segmented value={appearance.ecgPaper} onChange={(v) => update({ ecgPaper: v })} options={[{ value: "pink", label: "Pink" }, { value: "green", label: "Green" }, { value: "grey", label: "Grey" }]} /></Row>
        <Row label="Density"><Segmented value={appearance.density} onChange={(v) => update({ density: v })} options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]} /></Row>
        <Row label="Contrast"><Segmented value={appearance.contrast} onChange={(v) => update({ contrast: v })} options={[{ value: "normal", label: "Normal" }, { value: "high", label: "High" }]} /></Row>
      </div>
    </Card>
  );
}

const INTEGRATIONS = [
  ["Hospital information system (HIS)", "HL7 v2: ADT in (patients), ORM in (orders), ORU out (signed reports)", "Connected"],
  ["FHIR R4", "Patient, ServiceRequest, DiagnosticReport, Observation", "Available"],
  ["PACS / VNA", "DICOM 12-lead ECG waveform store and query", "Connected"],
  ["ECG machines", "Schiller SEMA, GE MUSE XML, Philips XML, DICOM, HL7 aECG, SCP-ECG", "4 machines"],
  ["Single sign-on", "Active Directory / SAML / OIDC, two-factor", "Connected"],
  ["MED AI", "Signed ECG findings shown in the MED AI patient record", "Available"],
];

function Integrations() {
  return (
    <Card>
      <CardHeader title="Integrations" description="Simulated statuses for the demo" icon={<Plug />} />
      <div className="card-pad space-y-2">
        {INTEGRATIONS.map(([name, what, status]) => (
          <div key={name} className="flex flex-col gap-1 rounded-xl border bg-card/70 p-3 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1"><div className="text-sm font-medium">{name}</div><div className="text-[0.78rem] text-muted-foreground">{what}</div></div>
            <Badge tone={status === "Available" ? "neutral" : "success"}>{status}</Badge>
          </div>
        ))}
      </div>
    </Card>
  );
}

function UsersSection() {
  return (
    <Card>
      <CardHeader title="Users & roles" description="Who may do what" icon={<Users />} />
      <div className="card-pad space-y-2">
        {DEMO_USERS.map((u) => (
          <div key={u.name} className="flex items-center gap-3 rounded-xl border bg-card/70 p-3">
            <Avatar name={u.name} size="sm" />
            <div className="flex-1"><div className="text-sm font-medium">{u.name}</div><div className="text-[0.78rem] text-muted-foreground">{u.title}</div></div>
            <Badge tone="outline" className="capitalize">{u.role}</Badge>
          </div>
        ))}
        <p className="pt-1 text-[0.75rem] text-muted-foreground">Cardiologists read and sign. Technicians record, upload and send for reading. Administrators manage settings and integrations; they cannot sign.</p>
      </div>
    </Card>
  );
}

function About() {
  const { data: c } = useCatalog();
  return (
    <Card>
      <CardHeader title="About Cardiotic AI" icon={<Info />} />
      <div className="card-pad space-y-2 text-[0.82rem]">
        <div className="flex justify-between gap-3"><span className="text-muted-foreground">Engine</span><span>{c?.engine.engine} {c?.engine.version} · models {c?.engine.models_version}</span></div>
        <div className="flex justify-between gap-3"><span className="text-muted-foreground">Intended use</span><span className="text-right">{c?.engine.intended_use}</span></div>
        <div className="flex justify-between gap-3"><span className="text-muted-foreground">Demo data</span><span className="text-right">PTB-XL (CC BY 4.0), Chapman–Shaoxing (CC0), MIT-BIH (ODC-By 1.0)</span></div>
        <p className="pt-2 text-[0.75rem] text-muted-foreground">{c?.disclaimer}</p>
      </div>
    </Card>
  );
}

export default function SettingsPage() {
  const { section = "site" } = useParams();
  const body = { site: <Site />, appearance: <Appearance />, integrations: <Integrations />, users: <UsersSection />, about: <About /> }[section] ?? <Site />;
  return (
    <div className="animate-fade-in">
      <PageHeader title="Settings" />
      <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
        <nav className="flex gap-1 overflow-x-auto lg:flex-col">
          {SECTIONS.map((s) => (
            <NavLink key={s.id} to={`/settings/${s.id}`} className={({ isActive }) => cn("flex shrink-0 items-center gap-2 rounded-full px-3 py-2 text-sm font-medium", isActive || (section === s.id) ? "bg-strong text-strong-foreground" : "text-muted-foreground hover:bg-muted")}>
              <s.icon className="size-4" /> {s.label}
            </NavLink>
          ))}
        </nav>
        <div className="min-w-0">{body}</div>
      </div>
    </div>
  );
}
