/** Settings screens that talk to the Cardiotic server: site, users and the HIS connection. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, FolderInput, Plug, Plus, ShieldCheck, Trash2, Users } from "lucide-react";
import { TwoFactorSetup } from "@/features/auth/TwoFactorSetup";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";
import { useDemo } from "@/app/demo-store";
import { Avatar, Badge, Button, Card, CardHeader, Input, Select, SwitchRow } from "@/components/ui";
import { fmtDateTime } from "@/lib/utils";
import { api, ApiError } from "@/lib/server";

const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Could not reach the server");

function Row({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 border-b py-4 last:border-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="max-w-md"><div className="text-sm font-medium">{label}</div>{hint && <div className="text-[0.78rem] text-muted-foreground">{hint}</div>}</div>
      <div>{children}</div>
    </div>
  );
}

interface EngineInfo { version: string; models_version: string; site_config?: { site_id: string; config_version: string; approved_by: string; approved_at: string; statements: string[] } }

export function ServerSite() {
  const { site, updateSite } = useDemo();
  const info = useQuery({ queryKey: ["engine-info"], queryFn: () => api<EngineInfo>("/models") });
  const sc = info.data?.site_config;
  return (
    <Card>
      <CardHeader title="Site" description="How this installation presents itself and sends reports" icon={<Building2 />} />
      <div className="px-[var(--card-pad)] pb-[var(--card-pad)]">
        <Row label="Site name" hint="Shown in the header, on sign-in and on every printed report.">
          <Input className="w-full sm:w-72" defaultValue={site.siteName} onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== site.siteName) { updateSite({ siteName: v }); toast.success("Site name saved"); } }} />
        </Row>
        <SwitchRow label="Send signed reports to the HIS automatically" description="HL7 ORU^R01, queued as soon as a cardiologist signs. Delivery and retries are under Integrations." checked={site.autoSendHis} onCheckedChange={(v) => updateSite({ autoSendHis: v })} />
        <Row label="AI operating points" hint="The yes/no thresholds for each finding. They are set on this hospital's own validated ECGs and approved by the cardiology lead; the engine refuses a file made for other models.">
          {sc ? (
            <div className="text-right text-[0.8rem]"><Badge tone="success">Site configuration</Badge><div className="mt-1">{sc.site_id} · v{sc.config_version}</div><div className="text-muted-foreground">approved by {sc.approved_by}, {sc.approved_at} · {sc.statements.length} findings</div></div>
          ) : <div className="text-right text-[0.8rem]"><Badge tone="neutral">Model defaults</Badge><div className="mt-1 text-muted-foreground">no site configuration loaded</div></div>}
        </Row>
      </div>
    </Card>
  );
}

interface UserRow { id: number; username: string; name: string; role: string; title: string; active: number; source?: string; two_factor?: number }

export function ServerUsers() {
  const { user } = useDemo();
  const qc = useQueryClient();
  const admin = user?.role === "admin";
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<UserRow[]>("/users"), enabled: admin });
  const [form, setForm] = useState({ username: "", name: "", role: "technician", password: "", title: "" });
  const create = useMutation({
    mutationFn: () => api("/users", { method: "POST", json: form }),
    onSuccess: () => { toast.success(`User ${form.username} created`); setForm({ username: "", name: "", role: "technician", password: "", title: "" }); qc.invalidateQueries({ queryKey: ["users"] }); },
    onError: fail,
  });
  const resetTotp = useMutation({
    mutationFn: (username: string) => api(`/users/${username}`, { method: "PATCH", json: { reset_totp: true } }),
    onSuccess: () => { toast.success("Two-factor sign-in reset; the user sets it up again at the next sign-in"); qc.invalidateQueries({ queryKey: ["users"] }); },
    onError: fail,
  });
  const toggle = useMutation({
    mutationFn: (u: UserRow) => api(`/users/${u.username}`, { method: "PATCH", json: { active: !u.active } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
    onError: fail,
  });
  return (
    <Card>
      <CardHeader title="Users & roles" description="Who may do what" icon={<Users />} />
      <div className="card-pad space-y-2">
        {!admin && <p className="text-sm text-muted-foreground">Ask an administrator to add or change users.</p>}
        {(users.data ?? []).map((u) => (
          <div key={u.username} className="flex items-center gap-3 rounded-xl border bg-card/70 p-3">
            <Avatar name={u.name} size="sm" />
            <div className="flex-1"><div className="text-sm font-medium">{u.name} <span className="font-mono text-xs text-muted-foreground">{u.username}</span></div><div className="text-[0.78rem] text-muted-foreground">{[u.title, u.source === "ldap" ? "hospital directory" : u.source === "oidc" ? "identity provider" : "", u.two_factor ? "two-factor on" : ""].filter(Boolean).join(" · ")}</div></div>
            {admin && !!u.two_factor && <Button size="xs" variant="ghost" onClick={() => resetTotp.mutate(u.username)}>Reset two-factor</Button>}
            <Badge tone="outline" className="capitalize">{u.role}</Badge>
            <Button size="xs" variant="secondary" disabled={u.username === user?.username} onClick={() => toggle.mutate(u)}>{u.active ? "Deactivate" : "Activate"}</Button>
          </div>
        ))}
        {admin && (
          <form className="grid gap-2 rounded-xl border border-dashed p-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
            <Input aria-label="User name" placeholder="User name" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
            <Input aria-label="Full name" placeholder="Full name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })} options={[{ value: "cardiologist", label: "Cardiologist" }, { value: "technician", label: "Technician" }, { value: "admin", label: "Administrator" }]} />
            <Input aria-label="Title" placeholder="Title (optional)" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            <Input aria-label="Initial password" type="password" placeholder="Initial password (10+ characters)" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            <Button type="submit" variant="strong" disabled={create.isPending}>Add user</Button>
          </form>
        )}
        <p className="pt-1 text-[0.75rem] text-muted-foreground">Cardiologists read and sign. Technicians upload, match patients and send for reading. Administrators manage users, settings and the HIS connection; they cannot sign.</p>
      </div>
    </Card>
  );
}

interface His { enabled: boolean; host?: string; port?: number; facility?: string; application?: string; attach_pdf?: boolean; inbound?: { enabled: boolean; port: number } }
interface Outbox { id: number; ecg_id: string; status: string; attempts: number; last_error: string | null; created_at: string; sent_at: string | null }

export function ServerIntegrations() {
  const { user } = useDemo();
  return (
    <div className="space-y-4">
      <ServerFeeds />
      <ServerHis />
      {user?.role === "admin" && <ServerMonitors />}
    </div>
  );
}

function ServerHis() {
  const { user } = useDemo();
  const qc = useQueryClient();
  const admin = user?.role === "admin";
  const his = useQuery({ queryKey: ["his"], queryFn: () => api<His>("/his"), enabled: admin });
  const outbox = useQuery({ queryKey: ["outbox"], queryFn: () => api<Outbox[]>("/outbox"), enabled: admin || user?.role === "cardiologist", refetchInterval: 10000 });
  const [draft, setDraft] = useState<His | null>(null);
  const cur = draft ?? his.data ?? { enabled: false, host: "", port: 2575 };
  const save = useMutation({
    mutationFn: () => api<His>("/his", { method: "PUT", json: cur }),
    onSuccess: () => { toast.success("HIS connection saved"); setDraft(null); qc.invalidateQueries({ queryKey: ["his"] }); },
    onError: fail,
  });
  const retry = useMutation({ mutationFn: (id: number) => api(`/outbox/${id}/retry`, { method: "POST", json: {} }), onSuccess: () => qc.invalidateQueries({ queryKey: ["outbox"] }), onError: fail });
  return (
    <Card>
      <CardHeader title="Integrations" description="Hospital information system (HL7 v2 over MLLP)" icon={<Plug />} />
      <div className="card-pad space-y-4">
        {admin ? (
          <form className="grid gap-2 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
            <Input aria-label="HIS host" placeholder="HIS host" value={cur.host ?? ""} onChange={(e) => setDraft({ ...cur, host: e.target.value })} className="sm:col-span-2" />
            <Input aria-label="HIS port" type="number" placeholder="Port" value={cur.port ?? 2575} onChange={(e) => setDraft({ ...cur, port: Number(e.target.value) })} />
            <Input aria-label="Receiving facility" placeholder="Receiving facility" value={cur.facility ?? ""} onChange={(e) => setDraft({ ...cur, facility: e.target.value })} />
            <div className="sm:col-span-4"><SwitchRow label="Deliver signed reports to the HIS" description="HL7 ORU^R01 with the PDF report attached" checked={!!cur.enabled} onCheckedChange={(v) => setDraft({ ...cur, enabled: v })} /></div>
            <div className="sm:col-span-3"><SwitchRow label="Receive patients and ECG orders from the HIS" description={`ADT (register, update, merge) and ORM orders over MLLP, port ${cur.inbound?.port ?? 2576}`} checked={!!cur.inbound?.enabled} onCheckedChange={(v) => setDraft({ ...cur, inbound: { port: cur.inbound?.port ?? 2576, enabled: v } })} /></div>
            <Input aria-label="Inbound port" type="number" value={cur.inbound?.port ?? 2576} onChange={(e) => setDraft({ ...cur, inbound: { enabled: !!cur.inbound?.enabled, port: Number(e.target.value) } })} />
            <Button type="submit" variant="strong" className="sm:col-span-4" disabled={save.isPending}>Save HIS connection</Button>
          </form>
        ) : <p className="text-sm text-muted-foreground">Only an administrator can change the connection.</p>}
        <div>
          <div className="text-label mb-2">Recent deliveries</div>
          {(outbox.data ?? []).length === 0 && <p className="text-sm text-muted-foreground">Nothing queued yet. A message is queued when a cardiologist signs a report.</p>}
          <div className="space-y-1.5">
            {(outbox.data ?? []).slice(0, 12).map((o) => (
              <div key={o.id} className="flex items-center gap-2 rounded-lg border bg-card/70 px-3 py-2 text-[0.8rem]">
                <span className="font-mono text-xs">{o.ecg_id}</span>
                <Badge tone={o.status === "sent" ? "success" : o.status === "failed" ? "danger" : "warning"}>{o.status}</Badge>
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{o.last_error ?? (o.sent_at ? `acknowledged ${fmtDateTime(o.sent_at)}` : `queued ${fmtDateTime(o.created_at)}`)}</span>
                {admin && o.status !== "sent" && <Button size="xs" variant="ghost" onClick={() => retry.mutate(o.id)}>Retry now</Button>}
              </div>
            ))}
          </div>
        </div>
        <p className="text-[0.75rem] text-muted-foreground">Reports go out as HL7 v2.5.1 ORU^R01 with the PDF attached; a FHIR R4 bundle is available for each signed report.</p>
      </div>
    </Card>
  );
}


interface FolderFeed { name: string; path: string; location?: string; enabled?: boolean }
interface FeedStatus { received: number; failed: number; last_received?: string; last_error?: string; last_error_at?: string }
interface Feeds { folders: FolderFeed[]; dicom: { enabled: boolean; port: number; ae_title: string; location?: string }; status: Record<string, FeedStatus>; dicom_running: boolean }

export function useFeeds() {
  return useQuery({ queryKey: ["feeds"], queryFn: () => api<Feeds>("/feeds"), refetchInterval: 15000 });
}

export function FeedStatusList({ feeds }: { feeds?: Feeds }) {
  const entries = Object.entries(feeds?.status ?? {});
  if (!entries.length) return <p className="text-sm text-muted-foreground">No recording has arrived from a machine yet.</p>;
  return (
    <div className="space-y-1.5">
      {entries.map(([name, st]) => (
        <div key={name} className="flex items-start gap-2 rounded-lg border bg-card/70 px-3 py-2 text-[0.8rem]">
          <span className="min-w-0 flex-1"><span className="font-medium">{name}</span>
            <span className="block text-muted-foreground">{st.received} received{st.last_received ? ` · last ${fmtDateTime(st.last_received)}` : ""}{st.failed ? ` · ${st.failed} refused` : ""}</span>
            {st.last_error && <span className="block truncate text-danger-foreground" title={st.last_error}>{st.last_error}</span>}</span>
          <Badge tone={st.last_error && (!st.last_received || (st.last_error_at ?? "") > st.last_received) ? "warning" : "success"}>{st.last_error && (!st.last_received || (st.last_error_at ?? "") > st.last_received) ? "Check" : "Receiving"}</Badge>
        </div>
      ))}
    </div>
  );
}

export function ServerFeeds() {
  const { user } = useDemo();
  const qc = useQueryClient();
  const admin = user?.role === "admin";
  const feeds = useFeeds();
  const [draft, setDraft] = useState<Pick<Feeds, "folders" | "dicom"> | null>(null);
  const cur = draft ?? (feeds.data ? { folders: feeds.data.folders, dicom: feeds.data.dicom } : null);
  const save = useMutation({
    mutationFn: () => api("/feeds", { method: "PUT", json: cur }),
    onSuccess: () => { toast.success("Machine feeds saved"); setDraft(null); qc.invalidateQueries({ queryKey: ["feeds"] }); },
    onError: fail,
  });
  if (!cur) return null;
  const setFolder = (i: number, patch: Partial<FolderFeed>) => setDraft({ ...cur, folders: cur.folders.map((f, j) => (j === i ? { ...f, ...patch } : f)) });
  return (
    <Card>
      <CardHeader title="ECG machines" description="Recordings that arrive without anyone uploading them" icon={<FolderInput />} />
      <div className="card-pad space-y-4">
        {admin && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
            <div className="text-label">Export folders</div>
            {cur.folders.map((f, i) => (
              <div key={i} className="grid gap-2 sm:grid-cols-[1fr_2fr_1fr_auto]">
                <Input aria-label="Feed name" placeholder="Name, e.g. MUSE export" value={f.name} onChange={(e) => setFolder(i, { name: e.target.value })} />
                <Input aria-label="Folder path" placeholder="/inbox/muse" value={f.path} onChange={(e) => setFolder(i, { path: e.target.value })} />
                <Input aria-label="Location" placeholder="Location" value={f.location ?? ""} onChange={(e) => setFolder(i, { location: e.target.value })} />
                <Button type="button" variant="ghost" size="icon" aria-label="Remove folder" onClick={() => setDraft({ ...cur, folders: cur.folders.filter((_, j) => j !== i) })}><Trash2 /></Button>
              </div>
            ))}
            <Button type="button" variant="secondary" size="sm" onClick={() => setDraft({ ...cur, folders: [...cur.folders, { name: "", path: "", location: "" }] })}><Plus /> Add folder</Button>
            <div className="text-label pt-2">DICOM receiver</div>
            <div className="grid gap-2 sm:grid-cols-3">
              <Input aria-label="AE title" value={cur.dicom.ae_title} onChange={(e) => setDraft({ ...cur, dicom: { ...cur.dicom, ae_title: e.target.value } })} />
              <Input aria-label="DICOM port" type="number" value={cur.dicom.port} onChange={(e) => setDraft({ ...cur, dicom: { ...cur.dicom, port: Number(e.target.value) } })} />
              <Input aria-label="DICOM location" placeholder="Location" value={cur.dicom.location ?? ""} onChange={(e) => setDraft({ ...cur, dicom: { ...cur.dicom, location: e.target.value } })} />
            </div>
            <SwitchRow label="Receive ECGs over DICOM (C-STORE)" description={feeds.data?.dicom_running ? "Running" : "Stopped"} checked={cur.dicom.enabled} onCheckedChange={(v) => setDraft({ ...cur, dicom: { ...cur.dicom, enabled: v } })} />
            <Button type="submit" variant="strong" disabled={save.isPending}>Save machine feeds</Button>
          </form>
        )}
        <div>
          <div className="text-label mb-2">Status</div>
          <FeedStatusList feeds={feeds.data} />
        </div>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ sign-in and two-factor
const ROLES = ["cardiologist", "technician", "admin"] as const;
interface Ldap { enabled?: boolean; url?: string; base_dn?: string; user_filter?: string; bind_dn?: string; bind_password?: string; user_dn_template?: string; role_groups?: Record<string, string> }
interface Oidc { enabled?: boolean; display_name?: string; issuer?: string; client_id?: string; client_secret?: string; redirect_uri?: string; role_claim?: string; role_map?: Record<string, string> }
interface AuthSettings { require_2fa: boolean; ldap: Ldap; oidc: Oidc }

function Text({ label, value, onChange, type = "text", placeholder }: { label: string; value?: string; onChange: (v: string) => void; type?: string; placeholder?: string }) {
  return <Input aria-label={label} placeholder={placeholder ?? label} type={type} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />;
}

export function ServerSecurity() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["auth-settings"], queryFn: () => api<AuthSettings>("/auth-settings") });
  const [d, setD] = useState<AuthSettings | null>(null);
  const cur = d ?? q.data;
  const save = useMutation({
    mutationFn: () => api("/auth-settings", { method: "PUT", json: cur }),
    onSuccess: () => { toast.success("Sign-in settings saved"); setD(null); qc.invalidateQueries({ queryKey: ["auth-settings"] }); },
    onError: fail,
  });
  if (!cur) return null;
  const ldap = (p: Partial<Ldap>) => setD({ ...cur, ldap: { ...cur.ldap, ...p } });
  const oidc = (p: Partial<Oidc>) => setD({ ...cur, oidc: { ...cur.oidc, ...p } });
  const roleMap = cur.oidc.role_map ?? {};
  const valueFor = (role: string) => Object.entries(roleMap).find(([, r]) => r === role)?.[0] ?? "";
  const setValueFor = (role: string, v: string) => {
    const next = Object.fromEntries(Object.entries(roleMap).filter(([, r]) => r !== role));
    if (v.trim()) next[v.trim()] = role;
    oidc({ role_map: next });
  };
  return (
    <Card>
      <CardHeader title="Security" description="How people sign in" icon={<ShieldCheck />} />
      <form className="card-pad space-y-5" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <SwitchRow label="Require two-factor sign-in" description="Everyone signing in with a password also enters a code from an authenticator app. Sign-ins through the identity provider use its own two-factor." checked={cur.require_2fa} onCheckedChange={(v) => setD({ ...cur, require_2fa: v })} />
        <div className="space-y-2">
          <SwitchRow label="Active Directory / LDAP" description="People sign in with their hospital account; their directory groups decide their role." checked={!!cur.ldap.enabled} onCheckedChange={(v) => ldap({ enabled: v })} />
          {cur.ldap.enabled && (
            <div className="grid gap-2 sm:grid-cols-2">
              <Text label="Directory URL" placeholder="ldaps://dc1.hospital.local" value={cur.ldap.url} onChange={(v) => ldap({ url: v })} />
              <Text label="Users under (base DN)" placeholder="OU=Staff,DC=hospital,DC=local" value={cur.ldap.base_dn} onChange={(v) => ldap({ base_dn: v })} />
              <Text label="Service account DN" value={cur.ldap.bind_dn} onChange={(v) => ldap({ bind_dn: v })} />
              <Text label="Service account password" type="password" value={cur.ldap.bind_password} onChange={(v) => ldap({ bind_password: v })} />
              <Text label="User filter" placeholder="(sAMAccountName={username})" value={cur.ldap.user_filter} onChange={(v) => ldap({ user_filter: v })} />
              <div />
              {ROLES.map((r) => <Text key={r} label={`Group for ${r}s`} placeholder={`Group DN for ${r}s`} value={cur.ldap.role_groups?.[r]} onChange={(v) => ldap({ role_groups: { ...(cur.ldap.role_groups ?? {}), [r]: v } })} />)}
            </div>
          )}
        </div>
        <div className="space-y-2">
          <SwitchRow label="Single sign-on (OpenID Connect)" description="Azure AD / Entra ID, Keycloak, Okta and other OpenID Connect providers. A button appears on the sign-in page." checked={!!cur.oidc.enabled} onCheckedChange={(v) => oidc({ enabled: v })} />
          {cur.oidc.enabled && (
            <div className="grid gap-2 sm:grid-cols-2">
              <Text label="Button label" placeholder="e.g. Hospital account" value={cur.oidc.display_name} onChange={(v) => oidc({ display_name: v })} />
              <Text label="Issuer URL" placeholder="https://login.microsoftonline.com/<tenant>/v2.0" value={cur.oidc.issuer} onChange={(v) => oidc({ issuer: v })} />
              <Text label="Client ID" value={cur.oidc.client_id} onChange={(v) => oidc({ client_id: v })} />
              <Text label="Client secret" type="password" value={cur.oidc.client_secret} onChange={(v) => oidc({ client_secret: v })} />
              <Text label="Redirect URI" placeholder="https://cardiotic.hospital.local/api/auth/oidc/callback" value={cur.oidc.redirect_uri} onChange={(v) => oidc({ redirect_uri: v })} />
              <Text label="Role claim" placeholder="roles" value={cur.oidc.role_claim} onChange={(v) => oidc({ role_claim: v })} />
              {ROLES.map((r) => <Text key={r} label={`Claim value for ${r}s`} placeholder={`Claim value for ${r}s`} value={valueFor(r)} onChange={(v) => setValueFor(r, v)} />)}
            </div>
          )}
        </div>
        <Button type="submit" variant="strong" disabled={save.isPending}>Save sign-in settings</Button>
      </form>
    </Card>
  );
}

export function ServerAccount() {
  const { user } = useDemo();
  const [setting, setSetting] = useState(false);
  return (
    <Card>
      <CardHeader title="My account" description={`${user?.name} · ${user?.username}`} icon={<Users />} />
      <div className="card-pad space-y-3 text-sm">
        <div className="flex items-center justify-between gap-3">
          <div><div className="font-medium">Two-factor sign-in</div><div className="text-[0.78rem] text-muted-foreground">{user?.source === "oidc" ? "Handled by your identity provider." : "A code from your phone at every sign-in."}</div></div>
          {user?.two_factor ? <Badge tone="success">On</Badge> : user?.source !== "oidc" && !setting && <Button variant="secondary" onClick={() => setSetting(true)}>Set up</Button>}
        </div>
        {setting && !user?.two_factor && <TwoFactorSetup onDone={() => setSetting(false)} />}
        <p className="text-[0.75rem] text-muted-foreground">{user?.source === "ldap" ? "Your password is your hospital directory password." : user?.source === "oidc" ? "You sign in through the hospital identity provider." : "Lost your phone or password? An administrator can reset them."}</p>
      </div>
    </Card>
  );
}

interface LiveBedCfg { bed: string; unit: string; label?: string; mrn?: string; silent?: boolean | null }

export function ServerMonitors() {
  const qc = useQueryClient();
  const beds = useQuery({ queryKey: ["live-beds"], queryFn: () => api<LiveBedCfg[]>("/live/beds") });
  const [form, setForm] = useState({ bed: "", unit: "ICU", label: "", mrn: "" });
  const [token, setToken] = useState<{ bed: string; token: string } | null>(null);
  const add = useMutation({
    mutationFn: () => api<{ bed: string; device_token: string }>("/live/beds", { method: "POST", json: form }),
    onSuccess: (r) => { setToken({ bed: r.bed, token: r.device_token }); setForm({ bed: "", unit: form.unit, label: "", mrn: "" }); qc.invalidateQueries({ queryKey: ["live-beds"] }); },
    onError: fail,
  });
  const remove = useMutation({ mutationFn: (bed: string) => api(`/live/beds/${bed}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["live-beds"] }), onError: fail });
  return (
    <Card>
      <CardHeader title="Bedside monitors" description="Live Assist: each bed's monitor gateway streams ECG with its own device token" icon={<Plug />} />
      <div className="card-pad space-y-3">
        {(beds.data ?? []).map((b) => (
          <div key={b.bed} className="flex items-center gap-2 rounded-lg border bg-card/70 px-3 py-2 text-[0.82rem]">
            <span className="font-medium">{b.bed}</span><span className="text-muted-foreground">{b.unit}{b.label ? ` · ${b.label}` : ""}{b.mrn ? ` · ${b.mrn}` : ""}</span>
            <Button size="xs" variant="ghost" className="ml-auto" onClick={() => remove.mutate(b.bed)}><Trash2 /> Remove</Button>
          </div>
        ))}
        <form className="grid gap-2 sm:grid-cols-5" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
          <Input aria-label="Bed ID" placeholder="Bed ID, e.g. ICU-4" value={form.bed} onChange={(e) => setForm({ ...form, bed: e.target.value })} />
          <Select value={form.unit} onValueChange={(v) => setForm({ ...form, unit: v })} options={["ICU", "OT", "ER", "WARD"].map((u) => ({ value: u, label: u }))} />
          <Input aria-label="Bed label" placeholder="Label" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
          <Input aria-label="Patient MRN" placeholder="Patient MRN" value={form.mrn} onChange={(e) => setForm({ ...form, mrn: e.target.value })} />
          <Button type="submit" variant="strong" disabled={add.isPending}><Plus /> Connect bed</Button>
        </form>
        {token && (
          <div className="rounded-lg border border-success/40 bg-success-soft/40 p-3 text-[0.8rem]">
            <div className="font-medium">Device token for {token.bed} (shown once)</div>
            <code className="mt-1 block break-all font-mono text-xs" aria-label="Device token">{token.token}</code>
            <div className="mt-1 text-muted-foreground">Enter it in the monitor gateway (header X-Device-Token on POST /api/live/ingest).</div>
          </div>
        )}
      </div>
    </Card>
  );
}
