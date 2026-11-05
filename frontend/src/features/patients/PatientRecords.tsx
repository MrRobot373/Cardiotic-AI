/** Administrator tools for one patient: export everything held (data-subject request) and erase after the retention period. */
import { Download, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { useDemo } from "@/app/demo-store";
import { Button, Dialog, DialogContent, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/server";

export function PatientRecords({ id, mrn }: { id: string; mrn: string }) {
  const { user, serverMode, site } = useDemo();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const qc = useQueryClient();
  if (!serverMode || user?.role !== "admin") return null;
  const erase = async () => {
    try {
      await api(`/patients/${id}`, { method: "DELETE", json: { confirm_mrn: typed } });
      toast.success("Patient record erased");
      setOpen(false);
      await qc.invalidateQueries();
      navigate("/patients");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not reach the server");
    }
  };
  return (
    <>
      <Button variant="secondary" asChild><a href={`/api/patients/${id}/export`} download><Download /> Export data</a></Button>
      <Button variant="ghost" onClick={() => { setTyped(""); setError(""); setOpen(true); }} aria-label="Erase patient record"><Trash2 /> Erase</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent size="sm" title="Erase this patient's records" icon={<Trash2 />}
          description={`This removes the patient and every recording, review and report held here. It cannot be undone. Signed reports younger than ${site.retentionYears} years are protected by the retention period.`}
          footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button variant="strong" disabled={typed !== mrn} onClick={() => void erase()}>Erase permanently</Button></>}>
          <Field label={`Type the MRN (${mrn}) to confirm`} htmlFor="erase-mrn" error={error || undefined}>
            <Input id="erase-mrn" value={typed} onChange={(e) => { setTyped(e.target.value); setError(""); }} autoComplete="off" />
          </Field>
        </DialogContent>
      </Dialog>
    </>
  );
}
