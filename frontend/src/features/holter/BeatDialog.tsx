/** Relabel one Holter beat (cardiologist, before signing). The AI's class stays visible; the report uses the cardiologist's. */
import { useState } from "react";
import { toast } from "sonner";
import { Button, Dialog, DialogContent } from "@/components/ui";
import { BEAT_NAMES } from "@/data/clinical";
import type { Beat } from "@/data/types";
import { api, ApiError } from "@/lib/server";
import { cn } from "@/lib/utils";

const CLASSES = ["N", "S", "V", "F"] as const;

export function BeatDialog({ id, beat, aiClass, canEdit, onClose, onChanged }: {
  id: string; beat: Beat | null; aiClass: string; canEdit: boolean; onClose: () => void; onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const set = async (label: string | null) => {
    if (!beat) return;
    setBusy(true);
    try {
      await api(`/holter/${id}/beats`, { method: "PUT", json: { time_s: beat.time_s, label } });
      onChanged();
      onClose();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not reach the server");
    } finally {
      setBusy(false);
    }
  };
  const m = beat ? Math.floor(beat.time_s / 60) : 0;
  const s = beat ? (beat.time_s % 60).toFixed(1) : "0";
  return (
    <Dialog open={!!beat} onOpenChange={(v) => !v && onClose()}>
      <DialogContent size="sm" title={beat ? `Beat at ${m} min ${s} s` : "Beat"}
        description={beat ? `AI: ${BEAT_NAMES[aiClass] ?? aiClass} (${Math.round(beat.probability * 100)}%, ${beat.confidence}). Now counted as ${BEAT_NAMES[beat.class]}.` : undefined}>
        {canEdit ? (
          <div className="space-y-2">
            <div className="text-label">Count this beat as</div>
            <div className="grid grid-cols-2 gap-2">
              {CLASSES.map((c) => (
                <Button key={c} variant={beat?.class === c ? "strong" : "secondary"} disabled={busy} onClick={() => void set(c)} className={cn("justify-start")}>{BEAT_NAMES[c]}</Button>
              ))}
            </div>
            {beat && beat.class !== aiClass && <Button variant="ghost" size="sm" disabled={busy} onClick={() => void set(null)}>Undo: back to the AI's class ({BEAT_NAMES[aiClass]})</Button>}
          </div>
        ) : <p className="text-sm text-muted-foreground">Only a cardiologist can relabel beats, and not after the report is signed.</p>}
      </DialogContent>
    </Dialog>
  );
}
