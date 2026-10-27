import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { Check, ChevronRight, X } from "lucide-react";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cn } from "@/lib/utils";

/* ---------- Dialog ---------- */
export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  title, description, children, className, footer, size = "md", icon,
}: {
  title: ReactNode; description?: ReactNode; children?: ReactNode; className?: string; footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl"; icon?: ReactNode;
}) {
  const widths = { sm: "max-w-md", md: "max-w-lg", lg: "max-w-2xl", xl: "max-w-4xl" };
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-slate-950/40 backdrop-blur-[2px] data-[state=open]:animate-fade-in" />
      <DialogPrimitive.Content
        className={cn(
          "fixed left-1/2 top-[8vh] z-50 flex max-h-[84vh] w-[calc(100vw-2rem)] -translate-x-1/2 flex-col overflow-hidden rounded-xl border bg-card shadow-pop focus:outline-none data-[state=open]:animate-scale-in",
          widths[size], className,
        )}
      >
        <div className="flex items-start gap-3 border-b px-5 py-4">
          {icon && <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary-soft-foreground [&_svg]:size-[18px]">{icon}</div>}
          <div className="min-w-0 flex-1">
            <DialogPrimitive.Title className="text-base font-semibold tracking-tight">{title}</DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="mt-0.5 text-[0.8rem] text-muted-foreground">{description}</DialogPrimitive.Description>
            ) : (
              <DialogPrimitive.Description className="sr-only">{typeof title === "string" ? title : "Dialog"}</DialogPrimitive.Description>
            )}
          </div>
          <DialogPrimitive.Close className="-mr-1 rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Close">
            <X className="size-4" />
          </DialogPrimitive.Close>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 border-t bg-subtle px-5 py-3">{footer}</div>}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

/* ---------- Sheet (side drawer) ---------- */
export function SheetContent({
  title, description, children, className, footer, width = "max-w-xl", headerExtra,
}: { title: ReactNode; description?: ReactNode; children?: ReactNode; className?: string; footer?: ReactNode; width?: string; headerExtra?: ReactNode }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-slate-950/30 data-[state=open]:animate-fade-in" />
      <DialogPrimitive.Content
        className={cn("fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l bg-card shadow-pop focus:outline-none data-[state=open]:animate-slide-in-right", width, className)}
      >
        <div className="flex items-start gap-3 border-b px-5 py-4">
          <div className="min-w-0 flex-1">
            <DialogPrimitive.Title className="truncate text-base font-semibold tracking-tight">{title}</DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description asChild><div className="mt-0.5 text-[0.8rem] text-muted-foreground">{description}</div></DialogPrimitive.Description>
            ) : (
              <DialogPrimitive.Description className="sr-only">Details</DialogPrimitive.Description>
            )}
          </div>
          {headerExtra}
          <DialogPrimitive.Close className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Close">
            <X className="size-4" />
          </DialogPrimitive.Close>
        </div>
        <div className="flex-1 overflow-y-auto">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 border-t bg-subtle px-5 py-3">{footer}</div>}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

/* ---------- Dropdown menu ---------- */
export const DropdownMenu = DropdownPrimitive.Root;
export const DropdownMenuTrigger = DropdownPrimitive.Trigger;
export const DropdownMenuSub = DropdownPrimitive.Sub;
export const DropdownMenuRadioGroup = DropdownPrimitive.RadioGroup;

const menuSurface = "z-50 min-w-[12rem] overflow-hidden rounded-lg border bg-popover p-1 text-sm text-foreground shadow-pop data-[state=open]:animate-scale-in";
const itemCls = "relative flex cursor-default select-none items-center gap-2 rounded-md px-2 py-1.5 outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-muted data-[disabled]:opacity-50 [&_svg]:size-4 [&_svg]:text-muted-foreground";

export function DropdownMenuContent({ className, align = "end", ...props }: ComponentPropsWithoutRef<typeof DropdownPrimitive.Content>) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content sideOffset={6} align={align} className={cn(menuSurface, className)} {...props} />
    </DropdownPrimitive.Portal>
  );
}

export function DropdownMenuItem({ className, danger, ...props }: ComponentPropsWithoutRef<typeof DropdownPrimitive.Item> & { danger?: boolean }) {
  return <DropdownPrimitive.Item className={cn(itemCls, danger && "text-danger data-[highlighted]:bg-danger-soft [&_svg]:text-danger", className)} {...props} />;
}

export function DropdownMenuRadioItem({ className, children, ...props }: ComponentPropsWithoutRef<typeof DropdownPrimitive.RadioItem>) {
  return (
    <DropdownPrimitive.RadioItem className={cn(itemCls, "pl-7", className)} {...props}>
      <span className="absolute left-2 flex size-4 items-center justify-center">
        <DropdownPrimitive.ItemIndicator><Check className="!text-primary" /></DropdownPrimitive.ItemIndicator>
      </span>
      {children}
    </DropdownPrimitive.RadioItem>
  );
}

export function DropdownMenuSubTrigger({ className, children, ...props }: ComponentPropsWithoutRef<typeof DropdownPrimitive.SubTrigger>) {
  return (
    <DropdownPrimitive.SubTrigger className={cn(itemCls, "data-[state=open]:bg-muted", className)} {...props}>
      {children}
      <ChevronRight className="ml-auto" />
    </DropdownPrimitive.SubTrigger>
  );
}

export function DropdownMenuSubContent({ className, ...props }: ComponentPropsWithoutRef<typeof DropdownPrimitive.SubContent>) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.SubContent sideOffset={6} className={cn(menuSurface, className)} {...props} />
    </DropdownPrimitive.Portal>
  );
}

export function DropdownMenuLabel({ className, ...props }: ComponentPropsWithoutRef<typeof DropdownPrimitive.Label>) {
  return <DropdownPrimitive.Label className={cn("px-2 py-1.5 text-xs text-muted-foreground", className)} {...props} />;
}

export function DropdownMenuSeparator({ className }: { className?: string }) {
  return <DropdownPrimitive.Separator className={cn("-mx-1 my-1 h-px bg-border", className)} />;
}

/* ---------- Popover ---------- */
export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export const PopoverClose = PopoverPrimitive.Close;

export function PopoverContent({ className, align = "center", ...props }: ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content sideOffset={8} align={align} className={cn("z-50 w-72 rounded-xl border bg-popover p-4 text-sm shadow-pop outline-none data-[state=open]:animate-scale-in", className)} {...props} />
    </PopoverPrimitive.Portal>
  );
}

/* ---------- Tooltip ---------- */
export const TooltipProvider = TooltipPrimitive.Provider;

export function Tooltip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "right" | "bottom" | "left" }) {
  if (!content) return <>{children}</>;
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content side={side} sideOffset={6} className="z-[60] max-w-xs rounded-md bg-foreground px-2 py-1 text-xs text-background shadow-pop data-[state=delayed-open]:animate-fade-in">
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
