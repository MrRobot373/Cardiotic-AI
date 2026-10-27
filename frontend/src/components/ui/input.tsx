import { forwardRef, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const base =
  "flex w-full rounded-lg border border-input bg-card/90 px-3 text-sm text-foreground shadow-xs transition-colors placeholder:text-muted-foreground/70 focus-visible:border-primary/60 focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/15 disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-danger";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  icon?: ReactNode;
  suffix?: ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(({ className, icon, suffix, ...props }, ref) => {
  if (!icon && !suffix) return <input ref={ref} className={cn(base, "h-9", className)} {...props} />;
  return (
    <div className={cn("relative flex items-center", className)}>
      {icon && <span className="pointer-events-none absolute left-3 text-muted-foreground [&_svg]:size-4">{icon}</span>}
      <input ref={ref} className={cn(base, "h-9", icon && "pl-9", suffix && "pr-10")} {...props} />
      {suffix && <span className="absolute right-2 flex items-center">{suffix}</span>}
    </div>
  );
});
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(base, "min-h-[84px] py-2 leading-relaxed", className)} {...props} />
));
Textarea.displayName = "Textarea";
