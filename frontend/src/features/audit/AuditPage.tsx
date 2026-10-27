import { ScrollText } from "lucide-react";
import { useDemo } from "@/app/demo-store";
import { Card, EmptyState, PageHeader, Table, TBody, TD, TH, THead, TR } from "@/components/ui";
import { fmtDateTime } from "@/lib/utils";

export default function AuditPage() {
  const { audit } = useDemo();
  return (
    <div className="animate-fade-in">
      <PageHeader title="Audit log" description="Who did what, when. In the product this log is append-only, signed and kept for the legally required period (DPDP Act 2023, HIPAA)." />
      <Card className="overflow-hidden">
        {audit.length === 0 ? <EmptyState icon={<ScrollText />} title="No events yet" description="Review an ECG, accept a finding or sign a report and it appears here." /> : (
          <Table>
            <THead><TR><TH>When</TH><TH>User</TH><TH>Action</TH><TH>Record</TH></TR></THead>
            <TBody>{audit.map((e, i) => <TR key={i}><TD className="whitespace-nowrap text-muted-foreground">{fmtDateTime(e.at)}</TD><TD className="font-medium">{e.user}</TD><TD>{e.action}</TD><TD className="font-mono text-xs">{e.target}</TD></TR>)}</TBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
