import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import * as SelectPrimitive from "@radix-ui/react-select";
import * as SliderPrimitive from "@radix-ui/react-slider";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { Check, ChevronDown } from "lucide-react";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cn } from "@/lib/utils";

/* ---------- Select ---------- */
export interface SelectOption {
  value: string;
  label: ReactNode;
  description?: ReactNode;
  group?: string;
}

export function Select({
  value, onValueChange, options, placeholder = "Select…", className, disabled, id, size = "md",
}: {
  value?: string; onValueChange: (v: string) => void; options: SelectOption[]; placeholder?: string;
  className?: string; disabled?: boolean; id?: string; size?: "sm" | "md";
}) {
  const groups = options.reduce<Record<string, SelectOption[]>>((acc, o) => {
    (acc[o.group ?? ""] ||= []).push(o);
    return acc;
  }, {});
  return (
    <SelectPrimitive.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectPrimitive.Trigger
        id={id}
        className={cn(
          "flex w-full items-center justify-between gap-2 rounded-md border border-input bg-card px-3 text-left text-sm shadow-xs transition-colors focus:outline-none focus-visible:border-primary/60 focus-visible:ring-[3px] focus-visible:ring-ring/15 disabled:opacity-60 data-[placeholder]:text-muted-foreground",
          size === "sm" ? "h-8 text-[0.8rem]" : "h-9", className,
        )}
      >
        <span className="truncate"><SelectPrimitive.Value placeholder={placeholder} /></span>
        <SelectPrimitive.Icon><ChevronDown className="size-4 shrink-0 text-muted-foreground" /></SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content position="popper" sideOffset={6} className="z-[60] max-h-[min(22rem,var(--radix-select-content-available-height))] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg border bg-popover shadow-pop data-[state=open]:animate-scale-in">
          <SelectPrimitive.Viewport className="p-1">
            {Object.entries(groups).map(([group, opts]) => (
              <SelectPrimitive.Group key={group}>
                {group && <SelectPrimitive.Label className="px-2 pb-1 pt-2 text-[0.7rem] font-semibold uppercase tracking-wide text-muted-foreground">{group}</SelectPrimitive.Label>}
                {opts.map((o) => (
                  <SelectPrimitive.Item key={o.value} value={o.value} className="relative flex cursor-default select-none flex-col rounded-md py-1.5 pl-7 pr-2 text-sm outline-none data-[highlighted]:bg-muted">
                    <span className="absolute left-2 top-2 flex size-4 items-center justify-center">
                      <SelectPrimitive.ItemIndicator><Check className="size-4 text-primary" /></SelectPrimitive.ItemIndicator>
                    </span>
                    <SelectPrimitive.ItemText>{o.label}</SelectPrimitive.ItemText>
                    {o.description && <span className="text-xs text-muted-foreground">{o.description}</span>}
                  </SelectPrimitive.Item>
                ))}
              </SelectPrimitive.Group>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}

/* ---------- Switch ---------- */
export function Switch({ className, ...props }: ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      className={cn("peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent bg-input transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary", className)}
      {...props}
    >
      <SwitchPrimitive.Thumb className="pointer-events-none block size-4 rounded-full bg-white shadow-sm ring-0 transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0" />
    </SwitchPrimitive.Root>
  );
}

export function SwitchRow({ label, description, checked, onCheckedChange, disabled }: { label: ReactNode; description?: ReactNode; checked: boolean; onCheckedChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-6 py-1">
      <span>
        <span className="block text-sm font-medium">{label}</span>
        {description && <span className="mt-0.5 block text-xs text-muted-foreground">{description}</span>}
      </span>
      <Switch checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} className="mt-0.5" />
    </label>
  );
}

/* ---------- Checkbox ---------- */
export function Checkbox({ className, ...props }: ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root className={cn("peer size-4 shrink-0 rounded border border-input bg-card shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground", className)} {...props}>
      <CheckboxPrimitive.Indicator className="flex items-center justify-center"><Check className="size-3" strokeWidth={3} /></CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

/* ---------- Slider ---------- */
export function Slider({ className, ...props }: ComponentPropsWithoutRef<typeof SliderPrimitive.Root>) {
  return (
    <SliderPrimitive.Root className={cn("relative flex w-full touch-none select-none items-center py-1.5", className)} {...props}>
      <SliderPrimitive.Track className="relative h-1.5 w-full grow overflow-hidden rounded-full bg-muted">
        <SliderPrimitive.Range className="absolute h-full bg-primary" />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb className="block size-4 rounded-full border-2 border-primary bg-card shadow transition-transform hover:scale-110 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring/20" />
    </SliderPrimitive.Root>
  );
}

/* ---------- Tabs ---------- */
export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;

export function TabsList({ className, ...props }: ComponentPropsWithoutRef<typeof TabsPrimitive.List>) {
  return <TabsPrimitive.List className={cn("inline-flex max-w-full items-center gap-1 overflow-x-auto rounded-full border border-border/60 bg-muted/80 p-1", className)} {...props} />;
}

export function TabsTrigger({ className, ...props }: ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-3.5 py-1 text-[0.8rem] font-medium text-muted-foreground transition-all hover:text-foreground data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-xs [&_svg]:size-3.5", className)}
      {...props}
    />
  );
}

/* ---------- Segmented control ---------- */
export function Segmented<T extends string>({
  value, onChange, options, className, size = "md",
}: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode; icon?: ReactNode }[]; className?: string; size?: "sm" | "md" }) {
  return (
    <div role="radiogroup" className={cn("inline-flex max-w-full items-center gap-0.5 overflow-x-auto rounded-full border border-border/60 bg-muted/80 p-0.5", className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full font-medium text-muted-foreground transition-all hover:text-foreground [&_svg]:size-3.5",
            size === "sm" ? "px-2.5 py-0.5 text-xs" : "px-3.5 py-1 text-[0.8rem]",
            value === o.value && "bg-card text-foreground shadow-xs",
          )}
        >
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  );
}
