import { ChevronLeft } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router";
import { Avatar, Badge } from "@/components/ui";
import { ageLabel } from "@/data/clinical";
import type { Patient } from "@/data/types";

export function PatientHeader({ patient, chips, actions, back = true }: { patient: Patient; chips?: ReactNode; actions?: ReactNode; back?: boolean }) {
  const navigate = useNavigate();
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      {back && (
        <button onClick={() => navigate(-1)} className="glass flex size-10 items-center justify-center rounded-full border border-white/70 shadow-card dark:border-white/[0.06]" aria-label="Back">
          <ChevronLeft className="size-4" />
        </button>
      )}
      <Avatar name={patient.name} size="lg" />
      <div className="min-w-0">
        <h1 className="truncate text-[1.35rem] font-semibold tracking-tight">{patient.name}</h1>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[0.82rem] text-muted-foreground">
          <span className="font-medium text-foreground num">{patient.mrn}</span>
          <span>{ageLabel(patient.age, patient.age_90_plus)} · {patient.sex === "F" ? "Female" : "Male"}</span>
          <Badge tone="outline" className="text-[0.65rem]">Demo patient</Badge>
        </div>
      </div>
      {chips && <div className="flex flex-wrap items-center gap-1.5">{chips}</div>}
      {actions && <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
