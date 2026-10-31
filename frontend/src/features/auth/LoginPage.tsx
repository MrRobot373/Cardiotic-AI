import { KeyRound, Lock, ShieldCheck, User } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { DEMO_USERS, useDemo } from "@/app/demo-store";
import { CardioticMark } from "@/components/layout/BrandMark";
import { Avatar, Button, Card, Field, Input } from "@/components/ui";
import { cn } from "@/lib/utils";

export function LoginPage() {
  const { signIn, site, serverMode, login, user: current, ready } = useDemo();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next") || "/";
  const [username, setUsername] = useState(serverMode ? "" : DEMO_USERS[0].username);
  const [busy, setBusy] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { if (serverMode && ready && current) navigate(next, { replace: true }); }, [serverMode, ready, current, navigate, next]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (serverMode) {
      if (!username.trim() || !password) return setError("Enter your user name and password.");
      setBusy(true);
      try {
        await login(username, password);
        navigate(next, { replace: true });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not sign in");
      } finally {
        setBusy(false);
      }
      return;
    }
    const u = DEMO_USERS.find((x) => x.username === username.trim().toLowerCase());
    if (!u) return setError("Unknown user name. Use your hospital account.");
    if (!password) return setError("Enter your password.");
    signIn(u);
    navigate(next, { replace: true });
  };
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-md animate-slide-up">
        <div className="mb-6 flex flex-col items-center text-center">
          <CardioticMark className="size-14 rounded-2xl" />
          <h1 className="mt-4 text-2xl font-semibold tracking-tight">Cardiotic AI</h1>
          <p className="mt-1 text-sm text-muted-foreground">AI-assisted ECG analysis · {site.siteName}</p>
        </div>
        <Card className="p-5">
          <form onSubmit={submit} className="space-y-3">
            <Field label="User name" htmlFor="username">
              <Input id="username" autoComplete="username" icon={<User />} value={username} onChange={(e) => { setUsername(e.target.value); setError(""); }} />
            </Field>
            <Field label="Password" htmlFor="password" error={error || undefined}>
              <Input id="password" type="password" autoComplete="current-password" icon={<Lock />} value={password} autoFocus onChange={(e) => { setPassword(e.target.value); setError(""); }} />
            </Field>
            <Button type="submit" variant="strong" className="w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</Button>
            {!serverMode && <Button type="button" variant="secondary" className="w-full" onClick={() => setPassword("sso")}><KeyRound /> Sign in with hospital SSO</Button>}
          </form>
          {!serverMode && <div className="mt-5">
            <div className="text-label mb-2">Recent on this workstation</div>
            <div className="flex flex-wrap gap-2">
              {DEMO_USERS.map((u) => (
                <button key={u.username} type="button" onClick={() => { setUsername(u.username); setError(""); }}
                  className={cn("flex items-center gap-2 rounded-full border bg-card/70 py-1 pl-1 pr-3 text-xs transition-colors hover:border-primary/40", username === u.username && "border-primary/60 bg-primary-soft/40")}>
                  <Avatar name={u.name} size="sm" /> <span className="font-medium">{u.name}</span>
                </button>
              ))}
            </div>
          </div>}
          <div className="mt-4 flex items-start gap-2 rounded-lg bg-subtle p-3 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-success" />
            <span>{serverMode ? "Sessions end after 15 minutes without activity. Five wrong passwords lock the account for 5 minutes." : "Hospital account (Active Directory) with two-factor authentication. Sessions lock after 15 minutes without activity."}</span>
          </div>
        </Card>
      </div>
    </div>
  );
}
