import * as LabelPrimitive from "@radix-ui/react-label";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Label({ className, ...props }: LabelPrimitive.LabelProps) {
  return <LabelPrimitive.Root className={cn("text-[0.8rem] font-medium text-foreground", className)} {...props} />;
}

export function Field({
  label, hint, error, htmlFor, children, className, required, action,
}: {
  label?: ReactNode; hint?: ReactNode; error?: ReactNode; htmlFor?: string; children: ReactNode;
  className?: string; required?: boolean; action?: ReactNode;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      {(label || action) && (
        <div className="flex items-center justify-between gap-2">
          {label && (
            <Label htmlFor={htmlFor}>
              {label}
              {required && <span className="ml-0.5 text-danger">*</span>}
            </Label>
          )}
          {action}
        </div>
      )}
      {children}
      {error ? <p className="text-xs text-danger">{error}</p> : hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
