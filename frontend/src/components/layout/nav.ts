import { Activity, BrainCircuit, FileText, HeartPulse, Inbox, ScrollText, Settings, Upload, Users, type LucideIcon } from "lucide-react";
import type { Role } from "@/app/demo-store";
import { serverMode } from "@/lib/server";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  roles?: Role[];
  badge?: "worklist";
}

/** Centre pill navigation — the reading workspace. */
export const PRIMARY_NAV: NavItem[] = [
  { to: "/", label: "Worklist", icon: Inbox, badge: "worklist" },
  { to: "/patients", label: "Patients", icon: Users },
  { to: "/holter", label: "Holter", icon: Activity },
  { to: "/monitoring", label: "Monitoring", icon: HeartPulse },
  { to: "/reports", label: "Reports", icon: FileText },
];

/** Left icon rail — capture, AI transparency and administration. */
export const RAIL_NAV: NavItem[] = [
  { to: "/upload", label: "Upload ECG", icon: Upload },
  { to: "/ai", label: "AI models & validation", icon: BrainCircuit },
  { to: "/audit", label: "Audit log", icon: ScrollText, roles: ["admin", "cardiologist"] },
  { to: "/settings", label: "Settings", icon: Settings },
];

export const visibleFor = (items: NavItem[], role?: Role) =>
  items.filter((i) => (!i.roles || (role && i.roles.includes(role))) && !(serverMode && i.to === "/monitoring"));

export const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Workspace", items: PRIMARY_NAV },
  { group: "Tools & administration", items: RAIL_NAV },
];
