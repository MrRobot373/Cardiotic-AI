import { AlertTriangle, CheckCircle2, CircleDashed, Clock3, RotateCcw } from "lucide-react";
import type { ReviewStatus } from "@/app/demo-store";
import { Badge } from "@/components/ui";
import { PRIORITY_META, type Priority } from "@/data/clinical";
import { cn } from "@/lib/utils";

export function PriorityBadge({ priority, className }: { priority: Priority; className?: string }) {
  const m = PRIORITY_META[priority];
  return <Badge tone={m.tone} className={className}>{priority === "critical" && <AlertTriangle />}{m.label}</Badge>;
}

const STATUS = {
  new: { label: "To read", tone: "primary" as const, icon: CircleDashed },
  in_review: { label: "In review", tone: "info" as const, icon: Clock3 },
  signed: { label: "Signed", tone: "success" as const, icon: CheckCircle2 },
  repeat: { label: "Repeat requested", tone: "warning" as const, icon: RotateCcw },
};

export function StatusBadge({ status, className }: { status: ReviewStatus; className?: string }) {
  const s = STATUS[status];
  return <Badge tone={s.tone} className={className}><s.icon />{s.label}</Badge>;
}

export function ConfidenceBadge({ level }: { level: string }) {
  const tone = level === "high" ? "success" : level === "moderate" ? "info" : "warning";
  return <Badge tone={tone} className="capitalize">{level}</Badge>;
}

/** Probability with the operating threshold marked — what "the AI is 87% sure" means against its cut-off. */
export function ProbabilityBar({ p, threshold, className }: { p: number; threshold?: number; className?: string }) {
  return (
    <div className={cn("relative h-1.5 w-full rounded-full bg-muted", className)} aria-label={`Probability ${Math.round(p * 100)}%`}>
      <div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(2, p * 100)}%` }} />
      {threshold !== undefined && <div className="absolute -top-1 h-3.5 w-0.5 rounded bg-foreground/60" style={{ left: `${threshold * 100}%` }} title={`Threshold ${Math.round(threshold * 100)}%`} />}
    </div>
  );
}
