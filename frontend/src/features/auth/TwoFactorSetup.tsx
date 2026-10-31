/** Set up two-factor sign-in: scan the QR code with an authenticator app, then confirm with one code. */
import { ShieldCheck } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useDemo } from "@/app/demo-store";
import { Button, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/server";

export function TwoFactorSetup({ onDone }: { onDone?: () => void }) {
  const { refreshMe } = useDemo();
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [qr, setQr] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const start = async () => {
    try {
      const s = await api<{ secret: string; uri: string }>("/me/totp/setup", { method: "POST", json: {} });
      setSetup(s);
      setQr(await QRCode.toDataURL(s.uri, { margin: 1, width: 200 }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not reach the server");
    }
  };
  useEffect(() => { void start(); }, []);
  const confirm = async () => {
    try {
      await api("/me/totp/enable", { method: "POST", json: { code } });
      toast.success("Two-factor sign-in is on");
      await refreshMe();
      onDone?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not reach the server");
    }
  };
  return (
    <div className="space-y-3">
      <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
        <li>Open an authenticator app on your phone (Microsoft Authenticator, Google Authenticator, FreeOTP…).</li>
        <li>Scan this code, or type the key by hand.</li>
        <li>Enter the 6-digit code the app shows.</li>
      </ol>
      {setup && (
        <div className="flex flex-col items-center gap-2 rounded-xl border bg-white p-3">
          {qr && <img src={qr} alt="QR code for the authenticator app" className="size-48" />}
          <code className="break-all text-center text-xs text-slate-700" aria-label="Set-up key">{setup.secret.replace(/(.{4})/g, "$1 ").trim()}</code>
        </div>
      )}
      <Field label="Code from the app" htmlFor="totp-code" error={error || undefined}>
        <Input id="totp-code" inputMode="numeric" autoComplete="one-time-code" maxLength={7} value={code} onChange={(e) => { setCode(e.target.value); setError(""); }} />
      </Field>
      <Button variant="strong" className="w-full" disabled={!setup || code.replace(/\s/g, "").length !== 6} onClick={confirm}><ShieldCheck /> Turn on two-factor sign-in</Button>
    </div>
  );
}
