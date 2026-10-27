import { ArrowRight, ShieldCheck } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router";
import { DEMO_USERS, useDemo } from "@/app/demo-store";
import { CardioticMark } from "@/components/layout/BrandMark";
import { Avatar, Card } from "@/components/ui";

export function LoginPage() {
  const { signIn } = useDemo();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next") || "/";
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-md animate-slide-up">
        <div className="mb-6 flex flex-col items-center text-center">
          <CardioticMark className="size-14 rounded-2xl" />
          <h1 className="mt-4 text-2xl font-semibold tracking-tight">Cardiotic AI</h1>
          <p className="mt-1 text-sm text-muted-foreground">AI-assisted ECG analysis · Demo Hospital, Pune</p>
        </div>
        <Card className="p-5">
          <div className="text-label mb-3">Sign in to the demo as</div>
          <div className="space-y-2">
            {DEMO_USERS.map((u) => (
              <button key={u.name} onClick={() => { signIn(u); navigate(next, { replace: true }); }}
                className="group flex w-full items-center gap-3 rounded-xl border bg-card/70 p-3 text-left transition-all hover:border-primary/40 hover:shadow-card">
                <Avatar name={u.name} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold">{u.name}</div>
                  <div className="text-xs text-muted-foreground">{u.title}{u.role === "cardiologist" ? " · can sign reports" : u.role === "technician" ? " · records and uploads ECGs" : " · settings, audit, integrations"}</div>
                </div>
                <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
              </button>
            ))}
          </div>
          <div className="mt-4 flex items-start gap-2 rounded-lg bg-subtle p-3 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-success" />
            <span>In the product, sign-in uses the hospital's accounts (Active Directory / SSO) with two-factor authentication. This demo has no server and no real patient data.</span>
          </div>
        </Card>
        <p className="mt-4 text-center text-[0.7rem] text-muted-foreground">Research use only — not a medical device.</p>
      </div>
    </div>
  );
}
