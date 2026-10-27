import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { PriorityBadge } from "@/components/clinical/badges";
import { Avatar, Badge, Card, Input, PageHeader, Table, TBody, TD, TH, THead, TR } from "@/components/ui";
import { ageLabel, PRIORITY_META, statementName } from "@/data/clinical";
import { useWorkItems } from "@/data/derived";
import { fmtRelative } from "@/lib/utils";

export default function PatientsPage() {
  const { items, catalog } = useWorkItems();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    if (!catalog) return [];
    return catalog.patients.map((p) => {
      const ecgs = items.filter((i) => i.patient.id === p.id).sort((a, b) => b.ecg.recorded_at.localeCompare(a.ecg.recorded_at));
      const holters = catalog.holters.filter((h) => h.patient_id === p.id);
      return { p, ecgs, holters, latest: ecgs[0] };
    }).filter((r) => `${r.p.name} ${r.p.mrn}`.toLowerCase().includes(q.toLowerCase()))
      .sort((a, b) => (a.latest && b.latest ? PRIORITY_META[a.latest.priority].rank - PRIORITY_META[b.latest.priority].rank : a.latest ? -1 : 1));
  }, [catalog, items, q]);
  return (
    <div className="animate-fade-in">
      <PageHeader title="Patients" description="Patients and demographics come from the hospital information system (ADT feed)."
        actions={<Input icon={<Search />} placeholder="Name or MRN" value={q} onChange={(e) => setQ(e.target.value)} className="w-64" />} />
      <Card className="overflow-hidden">
        <Table>
          <THead><TR><TH>Patient</TH><TH>Latest ECG</TH><TH>Key findings</TH><TH className="text-right">ECGs</TH><TH className="text-right">Holter</TH></TR></THead>
          <TBody>
            {rows.map(({ p, ecgs, holters, latest }) => (
              <TR key={p.id} className="cursor-pointer" onClick={() => navigate(`/patients/${p.id}`)}>
                <TD><div className="flex items-center gap-2.5"><Avatar name={p.name} size="sm" /><div><div className="font-medium">{p.name}</div><div className="text-[0.72rem] text-muted-foreground">{p.mrn} · {ageLabel(p.age, p.age_90_plus)} {p.sex}</div></div></div></TD>
                <TD>{latest ? <div className="flex items-center gap-2"><PriorityBadge priority={latest.priority} /><span className="text-[0.78rem] text-muted-foreground">{fmtRelative(latest.ecg.recorded_at)}</span></div> : <span className="text-muted-foreground">—</span>}</TD>
                <TD className="max-w-md">{latest ? <div className="flex flex-wrap gap-1">{latest.ecg.statements.filter((s) => !s.statement.startsWith("SUPER_") && s.statement !== "SR").slice(0, 3).map((s) => <Badge key={s.statement}>{statementName(s.statement)}</Badge>)}</div> : holters[0]?.findings[0]}</TD>
                <TD className="text-right num">{ecgs.length}</TD>
                <TD className="text-right num">{holters.length || "—"}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </div>
  );
}
