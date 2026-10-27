import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("glass rounded-2xl border border-white/70 text-card-foreground shadow-card dark:border-white/[0.06]", className)} {...props} />;
}

export function CardHeader({
  title, description, icon, actions, className,
}: { title: ReactNode; description?: ReactNode; icon?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start justify-between gap-3 px-[var(--card-pad)] pt-[var(--card-pad)]", className)}>
      <div className="flex min-w-0 items-start gap-3">
        {icon && <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-primary-soft text-primary-soft-foreground ring-1 ring-primary/10 [&_svg]:size-4">{icon}</div>}
        <div className="min-w-0">
          <h3 className="truncate text-[0.95rem] font-semibold tracking-tight">{title}</h3>
          {description && <p className="mt-0.5 text-[0.8rem] text-muted-foreground">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
    </div>
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("card-pad", className)} {...props} />;
}
