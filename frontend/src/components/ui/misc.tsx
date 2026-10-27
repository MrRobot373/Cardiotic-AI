import * as SeparatorPrimitive from "@radix-ui/react-separator";
import { Loader2 } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";
import { cn, initials } from "@/lib/utils";

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("skeleton h-4", className)} {...props} />;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-4 animate-spin text-muted-foreground", className)} />;
}

export function Separator({ className, orientation = "horizontal" }: { className?: string; orientation?: "horizontal" | "vertical" }) {
  return (
    <SeparatorPrimitive.Root
      orientation={orientation}
      className={cn("shrink-0 bg-border", orientation === "horizontal" ? "h-px w-full" : "h-full w-px", className)}
    />
  );
}

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd className={cn("inline-flex h-5 min-w-5 items-center justify-center rounded border bg-muted px-1 font-sans text-[0.65rem] font-medium text-muted-foreground", className)}>
      {children}
    </kbd>
  );
}

const AVATAR_TONES = [
  "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
  "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
  "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
  "bg-teal-100 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300",
  "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300",
];

export function Avatar({ name, size = "md", className }: { name: string; size?: "xs" | "sm" | "md" | "lg" | "xl"; className?: string }) {
  const hash = [...name].reduce((a, c) => a + c.charCodeAt(0), 0);
  const sizes = { xs: "size-6 text-[0.6rem]", sm: "size-7 text-[0.65rem]", md: "size-9 text-xs", lg: "size-11 text-sm", xl: "size-14 text-base" };
  return (
    <span className={cn("inline-flex shrink-0 select-none items-center justify-center rounded-full font-semibold", AVATAR_TONES[hash % AVATAR_TONES.length], sizes[size], className)}>
      {initials(name)}
    </span>
  );
}

export function EmptyState({
  icon, title, description, action, className, compact,
}: { icon?: ReactNode; title: ReactNode; description?: ReactNode; action?: ReactNode; className?: string; compact?: boolean }) {
  return (
    <div className={cn("flex flex-col items-center justify-center text-center", compact ? "px-4 py-8" : "px-6 py-14", className)}>
      {icon && (
        <div className="mb-3 flex size-11 items-center justify-center rounded-xl border bg-subtle text-muted-foreground shadow-xs [&_svg]:size-5">
          {icon}
        </div>
      )}
      <p className="text-sm font-semibold">{title}</p>
      {description && <p className="mt-1 max-w-sm text-[0.8rem] text-muted-foreground">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function PageHeader({
  title, description, actions, eyebrow, className,
}: { title: ReactNode; description?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-3 pb-6 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0">
        {eyebrow && <div className="text-label mb-1.5">{eyebrow}</div>}
        <h1 className="text-[1.45rem] font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Section({ title, description, children, actions, className }: { title: ReactNode; description?: ReactNode; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={cn("space-y-3", className)}>
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          {description && <p className="text-xs text-muted-foreground">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function KeyValue({ label, value, className }: { label: ReactNode; value: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-4 py-1.5 text-sm", className)}>
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}
