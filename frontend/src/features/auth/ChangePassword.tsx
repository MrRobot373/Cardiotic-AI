/** Choose a new password: first sign-in with an administrator-issued password, an expired password, or from My account. */
import { KeyRound } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useDemo } from "@/app/demo-store";
import { Button, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/server";

export function ChangePassword({ onDone }: { onDone?: () => void }) {
  const { refreshMe } = useDemo();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const mismatch = again !== "" && again !== next;
  const submit = async () => {
    setBusy(true);
    try {
      await api("/me/password", { method: "POST", json: { current: cur, new: next } });
      toast.success("Password changed");
      setCur(""); setNext(""); setAgain("");
      await refreshMe();
      onDone?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not reach the server");
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <Field label="Current password" htmlFor="pw-current"><Input id="pw-current" type="password" autoComplete="current-password" value={cur} onChange={(e) => { setCur(e.target.value); setError(""); }} /></Field>
      <Field label="New password" htmlFor="pw-new" hint="At least 10 characters; not your user name; not one of your last 5 passwords."><Input id="pw-new" type="password" autoComplete="new-password" value={next} onChange={(e) => { setNext(e.target.value); setError(""); }} /></Field>
      <Field label="New password again" htmlFor="pw-again" error={mismatch ? "The two passwords are different" : error || undefined}><Input id="pw-again" type="password" autoComplete="new-password" value={again} onChange={(e) => { setAgain(e.target.value); setError(""); }} /></Field>
      <Button type="submit" variant="strong" className="w-full" disabled={busy || !cur || next.length < 10 || next !== again}><KeyRound /> Change password</Button>
    </form>
  );
}
