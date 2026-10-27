/** Shapes of the demo dataset (public/demo, built by scripts/build_demo_data.py from real engine output). */

export type Sex = "M" | "F";

export interface Patient {
  id: string;
  name: string;
  mrn: string;
  age: number | null;
  age_90_plus: boolean;
  sex: Sex;
  origin: string;
}

export interface Source {
  dataset: string;
  record: string | number;
  licence: string;
  role: string;
}

export interface Statement {
  statement: string;
  probability: number;
  confidence: "high" | "moderate" | "low";
  threshold?: number;
}

export interface Measurements {
  ok: boolean;
  heart_rate_bpm?: number;
  rr_ms?: number;
  pr_ms?: number | null;
  qrs_ms?: number;
  qt_ms?: number | null;
  qtc_bazett_ms?: number | null;
  qtc_fridericia_ms?: number | null;
  qrs_axis_deg?: number;
  t_axis_deg?: number | null;
}

export interface EcgSummary {
  id: string;
  patient_id: string;
  recorded_at: string;
  location: string;
  ordered_by: string;
  device: string;
  source: Source;
  reference_statements: string[];
  statements: Statement[];
  measurements: Measurements;
  unusable_leads: string[];
  noisy_leads: string[];
  notes: string[];
}

export interface Fiducials {
  p_on: number | null;
  qrs_on: number;
  r: number;
  qrs_off: number;
  t_peak: number;
  t_end: number | null;
  fs: number;
}

export interface EcgDetail {
  id: string;
  fs: number;
  leads: Record<string, string>; // base64 int16 µV
  median: {
    fs: number;
    r: number;
    n_beats: number;
    leads: Record<string, string>;
    r_peaks_s: number[];
    in_median: boolean[];
    detection_lead: string;
  } | null;
  analysis: {
    engine: EngineInfo;
    input_notes: string[];
    processing_ms: number;
    result: {
      lead_quality: Record<string, "good" | "noisy" | "unusable">;
      measurements: Measurements & { fiducials?: Fiducials; beats_detected?: number; beats_in_median?: number; detection_lead?: string; rr_irregular?: boolean };
      statements: Statement[];
      notes: string[];
    };
  };
}

export interface EngineInfo {
  engine: string;
  version: string;
  models_version: string;
  intended_use: string;
  models: Record<string, { model: string; sha256: string }>;
}

export interface HolterSummary {
  id: string;
  patient_id: string;
  recorded_at: string;
  duration_s: number;
  lead: string;
  fs: number;
  source: Source;
  device: string;
  ordered_by: string;
  findings: string[];
  measurements: { heart_rate_bpm: number; rr_min_s: number; rr_max_s: number; rr_cv: number; beats_analysed: number; usable_fraction: number; beat_counts: Record<string, number> };
}

export interface Beat {
  time_s: number;
  class: "N" | "S" | "V" | "F";
  probability: number;
  confidence: string;
}

export interface RhythmSegment {
  start_s: number;
  end_s: number;
  rhythm: "N" | "A" | "O" | "~";
  probability: number;
  confidence: string;
  probabilities: Record<string, number>;
}

export interface HolterDetail {
  id: string;
  fs: number;
  n_samples: number;
  analysis: {
    engine: EngineInfo;
    input_notes: string[];
    processing_ms: number;
    result: {
      quality_segments: { start_s: number; end_s: number; quality: "good" | "noisy" | "unusable"; probability: number }[];
      beats: Beat[];
      rhythm_segments: RhythmSegment[];
      measurements: HolterSummary["measurements"];
      findings: string[];
    };
  };
  reference_beats: { t: number; c: string }[];
}

export interface Catalog {
  generated: string;
  engine: EngineInfo;
  patients: Patient[];
  ecgs: EcgSummary[];
  holters: HolterSummary[];
  statement_descriptions: Record<string, string>;
  disclaimer: string;
}
