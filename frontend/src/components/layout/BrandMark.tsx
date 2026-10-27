import { Link } from "react-router";
import { cn } from "@/lib/utils";

export function CardioticMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-9 shrink-0 rounded-xl shadow-xs", className)} aria-hidden>
      <defs>
        <linearGradient id="cm-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3B82F6" />
          <stop offset="1" stopColor="#1E3A8A" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#cm-g)" />
      <path d="M16 25s-8.5-5-8.5-11.2A4.8 4.8 0 0 1 16 11a4.8 4.8 0 0 1 8.5 2.8C24.5 20 16 25 16 25z" fill="none" stroke="#fff" strokeWidth="2" strokeLinejoin="round" />
      <path d="M9 16.5h3.5l1.5-3 2.5 6 1.8-4h4.7" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function BrandMark({ className, showText = true, site = "Demo Hospital, Pune" }: { className?: string; showText?: boolean; site?: string }) {
  return (
    <Link to="/" className={cn("flex min-w-0 items-center gap-2.5", className)}>
      <CardioticMark />
      {showText && (
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[1.05rem] font-semibold tracking-tight">Cardiotic AI</div>
          <div className="truncate text-[0.7rem] text-muted-foreground">{site}</div>
        </div>
      )}
    </Link>
  );
}
