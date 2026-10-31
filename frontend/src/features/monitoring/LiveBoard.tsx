/** Live Assist board (server): bedside-monitor ECG streams analysed every few seconds; advisory flags only. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, BellOff, Check, Flag, Info, Pause, WifiOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useAppearance } from "@/app/appearance";
import { useDemo } from "@/app/demo-store";
import { Badge, Button, Card, EmptyState, PageHeader, Segmented } from "@/components/ui";
import { api, ApiError } from "@/lib/server";
import { cn, fmtDateTime } from "@/lib/utils";

interface LiveFlag { id: string; kind: string; text: string; raised: string; last_seen: string; silent: boolean }
interface LiveBed {
  bed: string; unit: string; label: string; mrn: string; silent: boolean; status: string; offline_for_s: number | null;
  hr: number | null; rhythm: string | null; quality: string | null; reason: string | null; vitals: { spo2?: number; abp_sys?: number; abp_dia?: number }; flags: LiveFlag[];
}
interface Board { silent_site: boolean; beds: LiveBed[] }
const RHYTHM: Record<string, string> = { N: "Sinus rhythm", A: "Possible AF", O: "Other rhythm", "~": "Too noisy" };

function Trace({ bed, active }: { bed: string; active: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const { resolvedTheme } = useAppearance();
  const { data } = useQuery({ queryKey: ["live-trace", bed], queryFn: () => api<{ fs: number; samples: number[] }>(`/live/${bed}/trace?seconds=8`), refetchInterval: active ? 1000 : false });
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const w = c.clientWidth, h = c.clientHeight, dpr = Math.min(window.devicePixelRatio || 1, 2);
    c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
    const ctx = c.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = resolvedTheme === "dark" ? "#0b1220" : "#f8fafc";
    ctx.fillRect(0, 0, w, h);
    const s = data?.samples ?? [];
    if (s.length < 2) return;
    const sorted = [...s].sort((a, b) => a - b);
    const base = sorted[Math.floor(sorted.length / 2)];
    ctx.strokeStyle = "#10b981";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    s.forEach((v, i) => {
      const x = (i / (s.length - 1)) * w, y = h * 0.62 - (v - base) * h * 0.3;
      if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    });
    ctx.stroke();
  }, [data, resolvedTheme]);
  return <canvas ref={ref} className="h-24 w-full rounded-lg border border-black/5 dark:border-white/5" aria-label={`Live ECG trace, ${bed}`} />;
}

function BedCard({ b, canReview }: { b: LiveBed; canReview: boolean }) {
  const qc = useQueryClient();
  const ack = useMutation({
    mutationFn: (id: string) => api(`/live/${b.bed}/flags/${id}/ack`, { method: "POST", json: {} }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["live"] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not reach the server"),
  });
  const offline = b.status === "offline" || b.status === "waiting";
  return (
    <Card className={cn("p-4", b.flags.length > 0 && !offline && "border-warning/50")}>
      <div className="mb-2 flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <div className="font-semibold">{b.bed}{b.label && <span className="ml-1.5 text-sm font-normal text-muted-foreground">{b.label}</span>}</div>
          <div className="text-[0.75rem] text-muted-foreground">{b.unit}{b.mrn && ` · ${b.mrn}`}</div>
        </div>
        {b.silent && <Badge tone="neutral"><BellOff /> Silent mode</Badge>}
        {b.status === "offline" && <Badge tone="danger"><WifiOff /> Stream lost</Badge>}
        {b.status === "paused" && <Badge tone="warning"><Pause /> Analysis paused</Badge>}
        {b.status === "analysing" && <Badge tone="success"><Activity /> Analysing</Badge>}
        {(b.status === "starting" || b.status === "waiting") && <Badge tone="neutral">{b.status === "waiting" ? "Waiting for the monitor" : "Starting"}</Badge>}
      </div>
      {offline ? (
        <div className="flex h-24 items-center justify-center rounded-lg border border-dashed px-4 text-center text-[0.78rem] text-muted-foreground">
          {b.status === "offline" ? `No data for ${b.offline_for_s ?? "?"} s. Nothing is shown; check the bedside monitor.` : "The monitor gateway has not sent data yet."}
        </div>
      ) : <Trace bed={b.bed} active={!offline} />}
      {b.reason && <p className="mt-2 text-[0.78rem] text-warning-foreground">{b.reason}</p>}
      <div className="mt-3 flex items-end gap-5">
        <div><div className="text-label">Heart rate · AI beats</div><div className="text-[1.9rem] font-semibold leading-none num">{b.hr ? Math.round(b.hr) : "—"}</div></div>
        <div><div className="text-label">Rhythm</div><div className="text-sm font-medium">{b.rhythm ? RHYTHM[b.rhythm] ?? b.rhythm : "—"}</div></div>
        <div className="ml-auto text-right text-[0.75rem] text-muted-foreground">
          {b.vitals.spo2 !== undefined && <div>SpO₂ {b.vitals.spo2}%</div>}
          {b.vitals.abp_sys !== undefined && <div>ABP {b.vitals.abp_sys}/{b.vitals.abp_dia}</div>}
          {(b.vitals.spo2 !== undefined || b.vitals.abp_sys !== undefined) && <div>from the monitor</div>}
        </div>
      </div>
      {b.flags.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {b.flags.map((f) => (
            <div key={f.id} className="flex items-center gap-2 rounded-lg border border-warning/40 bg-warning-soft/40 px-2.5 py-1.5 text-[0.8rem]">
              <Flag className="size-3.5 shrink-0" />
              <span className="min-w-0 flex-1"><span className="font-medium">{f.text}</span><span className="block text-[0.7rem] text-muted-foreground">since {fmtDateTime(f.raised)}{f.silent ? " · silent mode (not shown to clinicians)" : ""}</span></span>
              {canReview && <Button size="xs" variant="secondary" onClick={() => ack.mutate(f.id)}><Check /> Reviewed</Button>}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export function LiveBoard() {
  const { user } = useDemo();
  const qc = useQueryClient();
  const [unit, setUnit] = useState("all");
  const { data } = useQuery({ queryKey: ["live"], queryFn: () => api<Board>("/live"), refetchInterval: 2000 });
  const silent = useMutation({
    mutationFn: (v: boolean) => api("/live/settings", { method: "PUT", json: { silent: v } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["live"] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not reach the server"),
  });
  const beds = (data?.beds ?? []).filter((b) => unit === "all" || b.unit === unit);
  const units = Array.from(new Set((data?.beds ?? []).map((b) => b.unit)));
  return (
    <div className="animate-fade-in">
      <PageHeader eyebrow="Live Assist" title="Monitoring"
        description="Advisory review flags for connected OT and ICU beds. This board never replaces, delays or silences the bedside monitor's alarms, and it looks different from them on purpose."
        actions={units.length > 1 ? <Segmented value={unit} onChange={setUnit} options={[{ value: "all", label: "All beds" }, ...units.map((u) => ({ value: u, label: u }))]} /> : undefined} />
      {data?.silent_site && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-dashed bg-card/60 p-3 text-[0.8rem] text-muted-foreground">
          <BellOff className="size-4 shrink-0" />
          <span className="min-w-0 flex-1">Silent mode: analysis runs and flags are recorded, but clinicians do not see them until the site's silent-mode study is complete.{user?.role === "admin" && " Administrators see them here."}</span>
          {user?.role === "admin" && <Button size="sm" variant="secondary" onClick={() => { if (confirm("Show advisory flags to clinicians at this site?")) silent.mutate(false); }}>Show flags to clinicians</Button>}
        </div>
      )}
      <div className="mb-4 flex items-start gap-2 rounded-xl border border-dashed bg-card/60 p-3 text-[0.78rem] text-muted-foreground">
        <Info className="mt-0.5 size-4 shrink-0" />
        Heart rate and rhythm come from the AI's analysis of the monitor's ECG (the last minute, every 5 s). SpO₂ and blood pressure are passed through from the monitor unchanged. Analysis pauses while the signal is noisy (diathermy, movement).
      </div>
      {beds.length === 0 ? (
        <EmptyState icon={<Activity />} title="No monitors connected" description={user?.role === "admin" ? "Connect a bed under Settings → Integrations → Bedside monitors." : "An administrator connects bedside monitors."} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {beds.map((b) => <BedCard key={b.bed} b={b} canReview={user?.role === "cardiologist" || user?.role === "technician"} />)}
        </div>
      )}
    </div>
  );
}
