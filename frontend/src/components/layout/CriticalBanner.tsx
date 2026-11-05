/** Critical results waiting to be read: shown on every screen until someone acknowledges them (server mode). */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Siren } from "lucide-react";
import { useEffect, useRef } from "react";
import { Link } from "react-router";
import { useDemo } from "@/app/demo-store";
import { Button } from "@/components/ui";
import { api } from "@/lib/server";

interface Item { id: number; at: string; recording_id: string; level: string; reason: string; location: string }

function beep() {
  try {
    const ctx = new AudioContext();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.frequency.value = 880;
    g.gain.value = 0.08;
    o.connect(g).connect(ctx.destination);
    o.start();
    o.stop(ctx.currentTime + 0.25);
    setTimeout(() => void ctx.close(), 400);
  } catch {
    /* no audio available: the banner still shows */
  }
}

export function CriticalBanner() {
  const { user, serverMode } = useDemo();
  const qc = useQueryClient();
  const reads = serverMode && (user?.role === "cardiologist" || user?.role === "technician");
  const q = useQuery({ queryKey: ["notifications"], queryFn: () => api<{ items: Item[]; sound: boolean }>("/notifications"), enabled: reads, refetchInterval: 10000 });
  const seen = useRef<Set<number> | null>(null);
  useEffect(() => {
    if (!q.data) return;
    const ids = new Set(q.data.items.map((i) => i.id));
    if (seen.current && q.data.sound && [...ids].some((i) => !seen.current!.has(i))) beep();
    seen.current = ids;
  }, [q.data]);
  if (!reads || !q.data?.items.length) return null;
  const ack = async (id: number) => {
    await api(`/notifications/${id}/ack`, { method: "POST", json: {} }).catch(() => undefined);
    void qc.invalidateQueries({ queryKey: ["notifications"] });
  };
  return (
    <div role="alert" aria-live="assertive" className="no-print mx-3 mb-2 space-y-1.5 md:mx-6">
      {q.data.items.slice(0, 3).map((n) => (
        <div key={n.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-danger/40 bg-danger-soft px-3 py-2 text-sm text-danger-foreground">
          <Siren className="size-4 shrink-0" />
          <span className="min-w-0 flex-1"><strong className="font-semibold">{n.level === "critical" ? "Critical ECG" : "Urgent ECG"}</strong> · {n.reason}{n.location ? ` · ${n.location}` : ""}</span>
          <Button size="xs" variant="strong" asChild><Link to={`/ecg/${n.recording_id}`} onClick={() => void ack(n.id)}>Open and acknowledge</Link></Button>
          <Button size="xs" variant="ghost" onClick={() => void ack(n.id)}>Acknowledge</Button>
        </div>
      ))}
      {q.data.items.length > 3 && <div className="px-1 text-xs text-muted-foreground">+{q.data.items.length - 3} more critical results waiting</div>}
    </div>
  );
}
