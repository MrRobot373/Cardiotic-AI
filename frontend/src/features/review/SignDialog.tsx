/** Signing asks the cardiologist to confirm who they are: password (or the two-factor code, if they have one). */
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useDemo } from "@/app/demo-store";
import { Button, Dialog, DialogContent, Field, Input } from "@/components/ui";

export function SignDialog({ open, onOpenChange, onConfirm }: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** Resolves null when signed, else the message to show. */
  onConfirm: (confirm: { password?: string; code?: string }) => Promise<string | null>;
}) {
  const { user } = useDemo();
  const [secret, setSecret] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const usesCode = !!user?.two_factor;
  const submit = async () => {
    setBusy(true);
    setError("");
    const msg = await onConfirm(usesCode && /^\d{6}$/.test(secret.replace(/\s/g, "")) ? { code: secret.replace(/\s/g, "") } : { password: secret });
    setBusy(false);
    if (msg) { setError(msg); setSecret(""); } else { setSecret(""); onOpenChange(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(v) => { if (!busy) { setError(""); setSecret(""); onOpenChange(v); } }}>
      <DialogContent size="sm" title="Confirm your signature" icon={<ShieldCheck />}
        description={user?.source === "oidc" ? "Your signature is your legal sign-off. If this asks for more, sign in again through the hospital identity provider." : "Your signature is your legal sign-off on this report. Enter your password to confirm it is you."}
        footer={<><Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button><Button variant="strong" onClick={submit} disabled={busy || !secret}><ShieldCheck /> Sign report</Button></>}>
        <form onSubmit={(e) => { e.preventDefault(); void submit(); }}>
          <Field label={usesCode ? "Password, or the 6-digit code from your phone" : "Password"} htmlFor="sign-confirm" error={error || undefined}>
            <Input id="sign-confirm" type="password" autoComplete="current-password" autoFocus value={secret} onChange={(e) => { setSecret(e.target.value); setError(""); }} />
          </Field>
        </form>
      </DialogContent>
    </Dialog>
  );
}
