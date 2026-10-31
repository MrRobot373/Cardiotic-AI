import { LogOut, Monitor, Moon, Palette, Settings, Sun, UserRound } from "lucide-react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { useAppearance } from "@/app/appearance";
import { DEMO_USERS, useDemo } from "@/app/demo-store";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem,
  DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger,
} from "@/components/ui";
import { initials } from "@/lib/utils";

export function UserMenu() {
  const { user, signIn, signOut, serverMode } = useDemo();
  const { appearance, update } = useAppearance();
  const navigate = useNavigate();
  if (!user) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex size-10 items-center justify-center rounded-xl bg-primary text-[0.8rem] font-semibold text-primary-foreground shadow-card ring-2 ring-white/60 transition-transform hover:scale-[1.03] dark:ring-white/10" aria-label="Account menu">
          {initials(user.name)}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-64">
        <DropdownMenuLabel>
          <div className="text-sm font-medium text-foreground">{user.name}</div>
          <div>{user.title}</div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {!serverMode && <DropdownMenuSub>
          <DropdownMenuSubTrigger><UserRound /> Switch user</DropdownMenuSubTrigger>
          <DropdownMenuSubContent>
            <DropdownMenuRadioGroup value={user.name} onValueChange={(v) => { const u = DEMO_USERS.find((d) => d.name === v); if (u) { signIn(u); toast.success(`Signed in as ${u.name}`); } }}>
              {DEMO_USERS.map((u) => <DropdownMenuRadioItem key={u.name} value={u.name}>{u.name} · {u.title}</DropdownMenuRadioItem>)}
            </DropdownMenuRadioGroup>
          </DropdownMenuSubContent>
        </DropdownMenuSub>}
        <DropdownMenuItem onSelect={() => navigate("/settings/appearance")}><Palette /> Appearance</DropdownMenuItem>
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>{appearance.theme === "dark" ? <Moon /> : appearance.theme === "system" ? <Monitor /> : <Sun />} Theme</DropdownMenuSubTrigger>
          <DropdownMenuSubContent>
            <DropdownMenuRadioGroup value={appearance.theme} onValueChange={(v) => update({ theme: v as "light" | "dark" | "system" })}>
              <DropdownMenuRadioItem value="light">Light</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="dark">Dark</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="system">System</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuItem onSelect={() => navigate("/settings")}><Settings /> Settings</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem danger onSelect={() => { signOut(); navigate("/login", { replace: true }); }}><LogOut /> Sign out</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
