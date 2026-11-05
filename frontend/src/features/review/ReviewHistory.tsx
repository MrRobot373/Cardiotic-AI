/** Every saved state of a review with what changed: who decided what, the signature, the amendment. Server mode. */
import { useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";
import { useDemo } from "@/app/demo-store";
import { Card, CardHeader } from "@/components/ui";
import { api } from "@/lib/server";
import { fmtDateTime } from "@/lib/utils";

interface Version { version: number; at: string; user: string; action: string; changes: string[] }

export function ReviewHistory({ id }: { id: string }) {
  const { serverMode, review } = useDemo();
  const v = review(id).version;
  const q = useQuery({ queryKey: ["review-history", id, v], queryFn: () => api<Version[]>(`/reviews/${id}/history`), enabled: serverMode });
  if (!serverMode || !q.data?.length) return null;
  return (
    <Card>
      <CardHeader title="History" description="Every saved change to this report" icon={<History />} />
      <ol className="card-pad max-h-72 space-y-2.5 overflow-y-auto text-[0.8rem]" aria-label="Review history">
        {[...q.data].reverse().map((h) => (
          <li key={h.version} className="border-l-2 border-border pl-3">
            <div className="font-medium">{h.action}</div>
            <div className="text-muted-foreground">{h.user} · {fmtDateTime(h.at)}</div>
            {h.changes.length > 0 && <ul className="mt-0.5 list-disc pl-4 text-muted-foreground">{h.changes.slice(0, 6).map((c) => <li key={c}>{c}</li>)}</ul>}
          </li>
        ))}
      </ol>
    </Card>
  );
}
