import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Menu, Moon, Search, Sun, Upload } from "lucide-react";
import { useState } from "react";
import { Link, Navigate, NavLink, Outlet, useLocation } from "react-router";
import { useAppearance } from "@/app/appearance";
import { useDemo } from "@/app/demo-store";
import { Button, Kbd, SheetContent, Tooltip } from "@/components/ui";
import { isOpen, useWorkItems } from "@/data/derived";
import { cn } from "@/lib/utils";
import { BrandMark } from "./BrandMark";
import { CommandPaletteProvider, usePalette } from "./CommandPalette";
import { NAV, PRIMARY_NAV, RAIL_NAV, visibleFor } from "./nav";
import { UserMenu } from "./UserMenu";
import { TwoFactorSetup } from "@/features/auth/TwoFactorSetup";

const iconBtn = "glass relative flex size-10 items-center justify-center rounded-xl border border-white/70 text-muted-foreground shadow-card transition-colors hover:text-foreground dark:border-white/[0.06] [&_svg]:size-[18px]";

function TopBar() {
  const palette = usePalette();
  const { resolvedTheme, update } = useAppearance();
  const { user } = useDemo();
  const { items } = useWorkItems();
  const [mobileOpen, setMobileOpen] = useState(false);
  const open = items.filter((i) => isOpen(i, items) && (i.priority === "critical" || i.priority === "urgent")).length;
  const primary = visibleFor(PRIMARY_NAV, user?.role);
  const isMac = typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);

  return (
    <header className="no-print sticky top-0 z-30 bg-background/70 px-3 py-3 backdrop-blur-md md:px-6 md:py-4">
      <div className="flex items-center gap-3">
        <DialogPrimitive.Root open={mobileOpen} onOpenChange={setMobileOpen}>
          <DialogPrimitive.Trigger asChild>
            <button className={cn(iconBtn, "lg:hidden")} aria-label="Open navigation"><Menu /></button>
          </DialogPrimitive.Trigger>
          <SheetContent title={<BrandMark />} width="max-w-[290px] left-0 right-auto border-l-0 border-r">
            <nav className="space-y-4 p-3">
              {NAV.map((g) => (
                <div key={g.group}>
                  <div className="text-label mb-1 px-2">{g.group}</div>
                  {visibleFor(g.items, user?.role).map((i) => (
                    <NavLink key={i.to} to={i.to} end={i.to === "/"} onClick={() => setMobileOpen(false)} className={({ isActive }) => cn("flex items-center gap-2.5 rounded-full px-3 py-2 text-sm font-medium", isActive ? "bg-strong text-strong-foreground" : "hover:bg-muted")}>
                      <i.icon className="size-4" /> {i.label}
                    </NavLink>
                  ))}
                </div>
              ))}
            </nav>
          </SheetContent>
        </DialogPrimitive.Root>

        <BrandMark className="shrink-0" />

        <nav className="glass mx-auto hidden items-center gap-1 rounded-full border border-white/70 p-1 shadow-card dark:border-white/[0.06] lg:flex">
          {primary.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"}
              className={({ isActive }) => cn("relative flex items-center gap-2 rounded-full px-4 py-2 text-[0.84rem] font-medium transition-all",
                isActive ? "bg-strong text-strong-foreground shadow-card" : "text-muted-foreground hover:bg-muted/80 hover:text-foreground")}>
              <item.icon className="size-4" strokeWidth={1.9} />
              {item.label}
              {item.badge === "worklist" && open > 0 && <span className="ml-0.5 rounded-full bg-danger px-1.5 text-[0.65rem] font-semibold leading-[1.1rem] text-white num">{open}</span>}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2 lg:ml-0">
          <Tooltip content={<span className="flex items-center gap-1">Search <Kbd className="bg-transparent text-background/80">{isMac ? "⌘K" : "Ctrl K"}</Kbd></span>}>
            <button className={iconBtn} onClick={palette.open} aria-label="Search"><Search /></button>
          </Tooltip>
          <Tooltip content={resolvedTheme === "dark" ? "Light theme" : "Dark theme"}>
            <button className={cn(iconBtn, "hidden sm:flex")} onClick={() => update({ theme: resolvedTheme === "dark" ? "light" : "dark" })} aria-label="Toggle theme">
              {resolvedTheme === "dark" ? <Sun /> : <Moon />}
            </button>
          </Tooltip>
          <Button variant="strong" className="hidden h-10 rounded-xl px-3.5 sm:inline-flex" asChild>
            <Link to="/upload"><Upload /> Upload ECG</Link>
          </Button>
          <UserMenu />
        </div>
      </div>
      <nav className="mt-3 flex gap-1 overflow-x-auto lg:hidden">
        {primary.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.to === "/"} className={({ isActive }) => cn("flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium", isActive ? "bg-strong text-strong-foreground" : "glass border text-muted-foreground")}>
            <item.icon className="size-3.5" /> {item.label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}

function Rail() {
  const { user } = useDemo();
  return (
    <aside className="no-print sticky top-[88px] hidden h-fit shrink-0 lg:block">
      <div className="glass flex flex-col items-center gap-1.5 rounded-full border border-white/70 p-1.5 shadow-card dark:border-white/[0.06]">
        {visibleFor(RAIL_NAV, user?.role).map((item) => (
          <Tooltip key={item.to} content={item.label} side="right">
            <span className="block">
              <NavLink to={item.to} aria-label={item.label}
                className={({ isActive }) => cn("flex size-10 items-center justify-center rounded-full transition-all",
                  isActive ? "bg-strong text-strong-foreground shadow-card" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
                <item.icon className="size-[18px]" strokeWidth={1.85} />
              </NavLink>
            </span>
          </Tooltip>
        ))}
        <div className="my-1 h-px w-6 bg-border" />
        <Tooltip content="Engine online · models verified" side="right">
          <span className="flex size-10 items-center justify-center"><span className="relative flex size-2"><span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60" /><span className="relative inline-flex size-2 rounded-full bg-success" /></span></span>
        </Tooltip>
      </div>
    </aside>
  );
}

/** This hospital requires two-factor sign-in: nothing else opens until it is set up. */
function EnrolTwoFactor() {
  const { signOut } = useDemo();
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="mb-4 flex flex-col items-center text-center">
          <BrandMark />
          <h1 className="mt-4 text-xl font-semibold">Set up two-factor sign-in</h1>
          <p className="mt-1 text-sm text-muted-foreground">Your hospital requires a code from your phone at every sign-in.</p>
        </div>
        <div className="rounded-2xl border bg-card p-5 shadow-card"><TwoFactorSetup /></div>
        <Button variant="ghost" className="mt-3 w-full" onClick={signOut}>Sign out</Button>
      </div>
    </div>
  );
}

export function AppShell() {
  const { user, ready } = useDemo();
  const location = useLocation();
  if (!ready) return <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">Loading…</div>;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  if (user.enrol_2fa) return <EnrolTwoFactor />;
  return (
    <CommandPaletteProvider>
      <div className="min-h-screen">
        <TopBar />
        <div className="mx-auto flex w-full max-w-[1680px] gap-4 px-3 pb-6 md:px-6">
          <Rail />
          <main className="min-w-0 flex-1 pb-2">
            <Outlet />
            <footer className="no-print mt-8 text-[0.7rem] text-muted-foreground">
              Cardiotic AI supports qualified clinicians. ECG results are drafts until reviewed and do not replace clinical judgement or the bedside monitor.
            </footer>
          </main>
        </div>
      </div>
    </CommandPaletteProvider>
  );
}
