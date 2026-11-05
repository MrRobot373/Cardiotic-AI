/** Find any recording in a large archive (server mode): by MRN, name or recording number; opens it even when it is not in the worklist's recent set. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { StatusBadge } from "@/components/clinical/badges";
import { Button, Card, CardHeader, Input } from "@/components/ui";
import { pinRecording } from "@/data/api";
import type { ReviewStatus } from "@/app/demo-store";
import { api } from "@/lib/server";
import { fmtDateTime } from "@/lib/utils";

interface Hit { id: string; kind: string; recorded_at: string; location: string; mrn: string; name: string; status: ReviewStatus; signed_by?: string }
interface Result { total: number; offset: number; limit: number; items: Hit[] }
const PAGE = 20;

export function FindRecords({ truncated, total }: { truncated?: boolean; total?: number }) {
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const res = useQuery({ queryKey: ["search", q, offset], queryFn: () => api<Result>(`/search?q=${encodeURIComponent(q)}&limit=${PAGE}&offset=${offset}`), enabled: q !== "", placeholderData: (p) => p });
  const open = async (h: Hit) => {
    pinRecording(h.id);
    await qc.invalidateQueries({ queryKey: ["catalog"] });
    navigate(h.kind === "holter" ? `/holter/${h.id}` : `/ecg/${h.id}`);
  };
  return (
    <Card className="mb-4">
      <CardHeader title="Find a recording" description={truncated ? `This archive holds ${total?.toLocaleString()} recordings; the lists show open and recent ones. Search finds the rest.` : "By patient name, MRN or recording number"} icon={<Search />} />
      <div className="card-pad space-y-3">
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setOffset(0); setQ(text.trim()); }}>
          <Input aria-label="Search recordings" placeholder="Name, MRN or E000123" value={text} onChange={(e) => setText(e.target.value)} />
          <Button type="submit" variant="strong" disabled={!text.trim()}>Search</Button>
        </form>
        {q !== "" && res.data && (
          <div className="space-y-1.5" aria-label="Search results">
            {res.data.items.length === 0 && <p className="text-sm text-muted-foreground">Nothing found for “{q}”.</p>}
            {res.data.items.map((h) => (
              <button key={h.id} type="button" onClick={() => void open(h)} className="flex w-full items-center gap-3 rounded-lg border bg-card/70 px-3 py-2 text-left text-[0.82rem] hover:bg-muted">
                <span className="font-mono text-xs">{h.id}</span>
                <span className="min-w-0 flex-1 truncate"><span className="font-medium">{h.name}</span> <span className="text-muted-foreground">{h.mrn} · {h.kind === "holter" ? "Holter" : "12-lead"} · {fmtDateTime(h.recorded_at)}</span></span>
                <StatusBadge status={h.status} />
              </button>
            ))}
            {res.data.total > PAGE && (
              <div className="flex items-center justify-between pt-1 text-xs text-muted-foreground">
                <span>{offset + 1}–{Math.min(offset + PAGE, res.data.total)} of {res.data.total}</span>
                <span className="flex gap-1.5">
                  <Button size="xs" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</Button>
                  <Button size="xs" variant="secondary" disabled={offset + PAGE >= res.data.total} onClick={() => setOffset(offset + PAGE)}>Next</Button>
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
