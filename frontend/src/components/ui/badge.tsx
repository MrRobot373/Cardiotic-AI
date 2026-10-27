import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex max-w-full items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[0.7rem] font-medium leading-4 [&_svg]:size-3",
  {
    variants: {
      tone: {
        neutral: "border-transparent bg-muted text-muted-foreground",
        primary: "border-transparent bg-primary-soft text-primary-soft-foreground",
        success: "border-transparent bg-success-soft text-success-foreground",
        warning: "border-transparent bg-warning-soft text-warning-foreground",
        danger: "border-transparent bg-danger-soft text-danger-foreground",
        info: "border-transparent bg-info-soft text-info-foreground",
        outline: "bg-transparent text-muted-foreground",
      },
      square: { true: "rounded-md" },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type Tone = NonNullable<VariantProps<typeof badgeVariants>["tone"]>;

export function Badge({ className, tone, square, ...props }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone, square }), className)} {...props} />;
}

export function Dot({ tone = "neutral", pulse, className }: { tone?: Tone; pulse?: boolean; className?: string }) {
  const color = { neutral: "bg-muted-foreground", primary: "bg-primary", success: "bg-success", warning: "bg-warning", danger: "bg-danger", info: "bg-info", outline: "bg-border" }[tone];
  return (
    <span className={cn("relative inline-flex size-2 shrink-0", className)}>
      {pulse && <span className={cn("absolute inline-flex size-full animate-ping rounded-full opacity-60", color)} />}
      <span className={cn("relative inline-flex size-2 rounded-full", color)} />
    </span>
  );
}
