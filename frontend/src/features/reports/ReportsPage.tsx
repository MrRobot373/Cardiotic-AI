import { CheckCircle2, FileText, Send } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { StatusBadge } from "@/components/clinical/badges";
import { Avatar, Badge, Button, Card, EmptyState, PageHeader, Segmented, Table, TBody, TD, TH, THead, TR } from "@/components/ui";
import { statementName } from "@/data/clinical";
import { useWorkItems } from "@/data/derived";
import { finalStatements } from "@/features/review/EcgReviewPage";
import { fmtDateTime } from "@/lib/utils";

export default function ReportsPage() {
  const { items } = useWorkItems();
  const [tab, setTab] = useState<"signed" | "draft">("signed");
  const rows = useMemo(() => items.filter((i) => (tab === "signed" ? i.review.status === "signed" : i.review.status !== "signed"))
    .sort((a, b) => (b.review.signedAt ?? b.ecg.recorded_at).localeCompare(a.review.signedAt ?? a.ecg.recorded_at)), [items, tab]);
  return (
    <div className="animate-fade-in">
      <PageHeader title="Reports" description="Signed reports go to the hospital information system as HL7 ORU^R01 (or FHIR DiagnosticReport) with the PDF. Drafts never leave Cardiotic AI."
        actions={<Segmented value={tab} onChange={setTab} options={[{ value: "signed", label: "Signed" }, { value: "draft", label: "Drafts" }]} />} />
      <Card className="overflow-hidden">
        {rows.length === 0 ? (
          <EmptyState icon={<FileText />} title={tab === "signed" ? "No signed reports yet" : "No drafts"} description={tab === "signed" ? "Open an ECG from the worklist, review the AI findings and sign it." : undefined}
            action={tab === "signed" ? <Button variant="strong" asChild><Link to="/">Go to worklist</Link></Button> : undefined} />
        ) : (
          <Table>
            <THead><TR><TH>Patient</TH><TH>Interpretation</TH><TH>{tab === "signed" ? "Signed" : "Recorded"}</TH><TH>Status</TH><TH>HIS delivery</TH><TH /></TR></THead>
            <TBody>
              {rows.map((i) => (
                <TR key={i.ecg.id}>
                  <TD><div className="flex items-center gap-2.5"><Avatar name={i.patient.name} size="sm" /><div><div className="font-medium">{i.patient.name}</div><div className="text-[0.72rem] text-muted-foreground">{i.patient.mrn}</div></div></div></TD>
                  <TD className="max-w-md text-[0.82rem]">{finalStatements(i.ecg.statements, i.review).map((c) => statementName(c)).join(" · ") || "—"}</TD>
                  <TD className="whitespace-nowrap text-muted-foreground">{fmtDateTime(i.review.signedAt ?? i.ecg.recorded_at)}{i.review.signedBy && <div className="text-[0.72rem]">{i.review.signedBy}</div>}</TD>
                  <TD><StatusBadge status={i.review.status} /></TD>
                  <TD>{i.review.status === "signed" ? <Badge tone="success"><CheckCircle2 /> ORU^R01 acknowledged</Badge> : <Badge tone="outline"><Send /> Not sent</Badge>}</TD>
                  <TD className="text-right"><Button size="xs" variant="secondary" asChild><Link to={`/ecg/${i.ecg.id}/report`}>Open</Link></Button></TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
