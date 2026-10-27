import { Command } from "cmdk";
import { Activity, FileHeart, Monitor, Moon, Search, Sun } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { useAppearance } from "@/app/appearance";
import { Avatar, Kbd } from "@/components/ui";
import { useCatalog } from "@/data/api";
import { statementName } from "@/data/clinical";
import { fmtRelative } from "@/lib/utils";
import { NAV } from "./nav";

const PaletteContext = createContext<{ open: () => void }>({ open: () => undefined });
export const usePalette = () => useContext(PaletteContext);

export function CommandPaletteProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { update } = useAppearance();
  const { data: c } = useCatalog();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const go = useCallback((to: string) => { setOpen(false); navigate(to); }, [navigate]);
  const run = (fn: () => void) => { setOpen(false); fn(); };
  const item = "flex cursor-default items-center gap-2.5 rounded-md px-2.5 py-2 text-sm aria-selected:bg-muted [&_svg]:size-4 [&_svg]:text-muted-foreground";
  const group = "px-1 py-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-[0.68rem] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-muted-foreground";
  const name = (pid: string) => c?.patients.find((p) => p.id === pid)?.name ?? pid;

  return (
    <PaletteContext.Provider value={{ open: () => setOpen(true) }}>
      {children}
      <Command.Dialog open={open} onOpenChange={setOpen} label="Search"
        overlayClassName="fixed inset-0 z-50 bg-slate-950/40 backdrop-blur-[2px]"
        contentClassName="fixed left-1/2 top-[14vh] z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border bg-popover shadow-pop animate-scale-in">
        <div className="flex items-center gap-2 border-b px-3.5">
          <Search className="size-4 text-muted-foreground" />
          <Command.Input placeholder="Search patients, ECGs, findings…" className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground" />
          <Kbd>Esc</Kbd>
        </div>
        <Command.List className="max-h-[60vh] overflow-y-auto p-1.5">
          <Command.Empty className="py-10 text-center text-sm text-muted-foreground">No results.</Command.Empty>
          <Command.Group heading="Patients" className={group}>
            {c?.patients.map((p) => (
              <Command.Item key={p.id} value={`patient ${p.name} ${p.mrn}`} onSelect={() => go(`/patients/${p.id}`)} className={item}>
                <Avatar name={p.name} size="xs" /><span className="font-medium">{p.name}</span>
                <span className="text-xs text-muted-foreground">{p.mrn}</span>
              </Command.Item>
            ))}
          </Command.Group>
          <Command.Group heading="ECGs" className={group}>
            {c?.ecgs.map((e) => (
              <Command.Item key={e.id} value={`ecg ${e.id} ${name(e.patient_id)} ${e.statements.map((s) => statementName(s.statement)).join(" ")}`} onSelect={() => go(`/ecg/${e.id}`)} className={item}>
                <FileHeart /><span className="font-medium">{name(e.patient_id)}</span>
                <span className="truncate text-xs text-muted-foreground">{e.statements.filter((s) => !s.statement.startsWith("SUPER_")).slice(0, 2).map((s) => statementName(s.statement)).join(", ")}</span>
                <span className="ml-auto shrink-0 text-xs text-muted-foreground">{fmtRelative(e.recorded_at)}</span>
              </Command.Item>
            ))}
            {c?.holters.map((h) => (
              <Command.Item key={h.id} value={`holter ${h.id} ${name(h.patient_id)}`} onSelect={() => go(`/holter/${h.id}`)} className={item}>
                <Activity /><span className="font-medium">{name(h.patient_id)}</span><span className="text-xs text-muted-foreground">Holter · {Math.round(h.duration_s / 60)} min</span>
              </Command.Item>
            ))}
          </Command.Group>
          <Command.Group heading="Go to" className={group}>
            {NAV.flatMap((g) => g.items).map((i) => (
              <Command.Item key={i.to} value={`go ${i.label}`} onSelect={() => go(i.to)} className={item}><i.icon /> {i.label}</Command.Item>
            ))}
          </Command.Group>
          <Command.Group heading="Theme" className={group}>
            <Command.Item value="theme light" onSelect={() => run(() => update({ theme: "light" }))} className={item}><Sun /> Light theme</Command.Item>
            <Command.Item value="theme dark" onSelect={() => run(() => update({ theme: "dark" }))} className={item}><Moon /> Dark theme</Command.Item>
            <Command.Item value="theme system" onSelect={() => run(() => update({ theme: "system" }))} className={item}><Monitor /> System theme</Command.Item>
          </Command.Group>
        </Command.List>
      </Command.Dialog>
    </PaletteContext.Provider>
  );
}
