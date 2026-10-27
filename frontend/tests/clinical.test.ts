import { qtcInterpretable, rangeFlag, statementName, triage } from "@/data/clinical";
import { holterAnalytics } from "@/data/holter";
import { effectiveMeasurements, finalStatements } from "@/features/review/EcgReviewPage";
import type { HolterDetail } from "@/data/types";

const m = (x: object) => ({ ok: true, heart_rate_bpm: 70, qrs_ms: 90, qtc_bazett_ms: 420, ...x });
const st = (...c: string[]) => c.map((statement) => ({ statement }));

describe("triage", () => {
  it("puts complete heart block, fast AF and long QTc first", () => {
    expect(triage(st("3AVB"), m({})).priority).toBe("critical");
    expect(triage(st("AFIB"), m({ heart_rate_bpm: 130 })).priority).toBe("critical");
    expect(triage(st("AFIB"), m({ heart_rate_bpm: 80 })).priority).toBe("urgent");
    expect(triage(st("SR"), m({ qtc_bazett_ms: 520 })).priority).toBe("critical");
  });
  it("never lets QTc drive triage with a wide QRS or pacing", () => {
    expect(triage(st("CLBBB"), m({ qrs_ms: 160, qtc_bazett_ms: 540 })).priority).toBe("urgent");
    expect(triage(st("PACE"), m({ qrs_ms: 110, qtc_bazett_ms: 560 })).priority).toBe("routine");
    expect(qtcInterpretable(m({ qrs_ms: 130 }))).toBe(false);
  });
  it("normal only when the AI says normal and nothing else", () => {
    expect(triage(st("SUPER_NORM", "NORM", "SR"), m({})).priority).toBe("normal");
    expect(triage(st("SR"), m({})).priority).toBe("routine");
    expect(triage(st("IMI"), m({})).reason).toBe("Inferior myocardial infarction");
  });
});

describe("ranges and names", () => {
  it("flags out-of-range values by sex", () => {
    expect(rangeFlag("qtc_bazett_ms", 455, "M")).toBe("high");
    expect(rangeFlag("qtc_bazett_ms", 455, "F")).toBeNull();
    expect(rangeFlag("pr_ms", 230)).toBe("high");
  });
  it("names statements and groups", () => {
    expect(statementName("SUPER_MI")).toBe("Myocardial infarction");
    expect(statementName("XYZ", { XYZ: "something rare" })).toBe("Something rare");
  });
});

describe("review edits", () => {
  const review = { status: "in_review" as const, decisions: { AFIB: "rejected" as const, IMI: "accepted" as const }, added: ["LVH"], edits: { qt_ms: 400, "cal.tEnd": 360 }, note: "" };
  it("recomputes QTc from an edited QT and ignores caliper positions", () => {
    const e = effectiveMeasurements({ ok: true, qt_ms: 380, rr_ms: 1000, qtc_bazett_ms: 380 }, review);
    expect(e.qt_ms).toBe(400);
    expect(e.qtc_bazett_ms).toBeCloseTo(400);
    expect(e.edited.has("cal.tEnd")).toBe(false);
  });
  it("final statements drop rejected, keep accepted and added, never groups", () => {
    const ai = [{ statement: "AFIB", probability: 0.9, confidence: "high" as const }, { statement: "IMI", probability: 0.8, confidence: "moderate" as const }, { statement: "SUPER_MI", probability: 0.8, confidence: "moderate" as const }];
    expect(finalStatements(ai, review)).toEqual(["IMI", "LVH"]);
  });
});

describe("holter analytics", () => {
  it("finds AF episodes, ventricular runs and pauses", () => {
    const beats = [0, 1, 2, 3, 3.5, 4, 4.5, 5.5, 8.0, 9].map((t, i) => ({ time_s: t, class: (i >= 4 && i <= 6 ? "V" : "N") as "N" | "V", probability: 0.9, confidence: "high" }));
    const d = {
      id: "x", fs: 100, n_samples: 6000, reference_beats: [],
      analysis: { engine: {} as never, input_notes: [], processing_ms: 1, result: {
        beats, quality_segments: [], findings: [],
        rhythm_segments: [{ start_s: 0, end_s: 30, rhythm: "A" as const, probability: 0.9, confidence: "high", probabilities: {} }, { start_s: 15, end_s: 45, rhythm: "A" as const, probability: 0.9, confidence: "high", probabilities: {} }],
        measurements: { heart_rate_bpm: 60, rr_min_s: 0.5, rr_max_s: 2.5, rr_cv: 0.3, beats_analysed: 10, usable_fraction: 1, beat_counts: { N: 7, V: 3 } },
      } },
    } as HolterDetail;
    const a = holterAnalytics(d);
    expect(a.episodes).toEqual([[0, 45]]);
    expect(a.events.find((e) => e.kind === "pvc_run")?.label).toBe("Ventricular run ×3");
    expect(a.events.filter((e) => e.kind === "pause")).toHaveLength(1);
  });
});
