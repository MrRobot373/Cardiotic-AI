"""Render ml/reports/RESULTS.md from the JSON results written by experiments.py."""

from __future__ import annotations

import json

from cardiotic_ml.paths import REPORTS_DIR


def _pct(v) -> str:
    return "—" if v is None or v != v else f"{100 * v:.1f}%"


def _load(name: str) -> dict | None:
    p = REPORTS_DIR / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def _class_table(rep: dict) -> list[str]:
    rows = ["| Class | Test beats/windows | Sensitivity (Se) | Positive predictivity (+P) | F1 |", "|---|---:|---:|---:|---:|"]
    for name, m in rep["per_class"].items():
        rows.append(f"| {name} | {m['support']:,} | {_pct(m['sensitivity'])} | {_pct(m['ppv'])} | {_pct(m['f1'])} |")
    return rows


def _confusion(rep: dict) -> list[str]:
    labels = rep["labels"]
    rows = ["| true ↓ / predicted → | " + " | ".join(labels) + " |", "|---|" + "---:|" * len(labels)]
    for name, row in zip(labels, rep["confusion"]):
        rows.append(f"| **{name}** | " + " | ".join(f"{v:,}" for v in row) + " |")
    return rows


def _num(v, unit: str = "", nd: int = 1) -> str:
    return "—" if v is None or v != v else f"{v:.{nd}f}{unit}"


ECG12_MEASURE_NAMES = {"heart_rate_bpm": ("Heart rate", "bpm"), "pr_ms": ("PR interval", "ms"), "qrs_ms": ("QRS duration", "ms"),
                       "qt_ms": ("QT interval", "ms"), "qtc_bazett_ms": ("QTc (Bazett)", "ms"),
                       "qrs_axis_deg": ("QRS axis", "°"), "t_axis_deg": ("T axis", "°")}


def _ningbo_train_n(result: dict) -> str:
    import re
    m = re.search(r"(\d+) training ECGs", result["model_card"]["data"])
    return f"{int(m.group(1)):,}" if m else "the"


def _ecg12_section() -> list[str]:
    out = []
    st = _load("ecg12_statements_v0.1")
    from cardiotic_ml.experiments_ecg12 import ADOPTED_MEASURE
    me = _load(f"ecg12_measurements_test_{ADOPTED_MEASURE}")
    tu = _load(f"ecg12_measurement_tuning_{ADOPTED_MEASURE}")
    if not (st or me):
        return out
    out += ["## 7. 12-lead ECG (AI model #4) — PTB-XL", "",
            "PTB-XL: 21,799 ten-second 12-lead ECGs from 18,869 patients, statements by up to two cardiologists. "
            "Official patient-wise folds: 1–8 train, 9 validation, 10 test (2,198 ECGs). Every choice was made on folds 1–9; "
            "fold 10 was scored once per version.", ""]
    if st:
        t = st["test"]
        out += ["### 7.1 Diagnostic statements (ML)", "",
                "| Task | Statements | Test macro-AUC | 95% CI (bootstrap) | Validation macro-AUC |", "|---|---:|---:|---|---:|"]
        for k in ("superclass", "diagnostic", "form", "rhythm", "all"):
            out.append(f"| {k} | {t[k]['n_labels']} | {t[k]['macro_auc']:.3f} | {t[k]['ci95'][0]:.3f}–{t[k]['ci95'][1]:.3f} | {st['val'][k]:.3f} |")
        out += ["", f"Reference: {st['benchmark_note']} Ours is one model for all tasks.", "",
                "Selected statements at the threshold chosen on validation (maximum F1):", "",
                "| Statement | Meaning | Test ECGs with it | AUC | Sensitivity | Specificity | PPV |", "|---|---|---:|---:|---:|---:|---:|"]
        from cardiotic_ml.experiments_ecg12 import KEY_STATEMENTS
        names = [f"SUPER_{c}" for c in ("NORM", "MI", "STTC", "CD", "HYP")] + KEY_STATEMENTS
        for n in names:
            m = st["per_label"].get(n)
            if m:
                desc = {"SUPER_NORM": "normal ECG (superclass)", "SUPER_MI": "myocardial infarction (superclass)",
                        "SUPER_STTC": "ST/T change (superclass)", "SUPER_CD": "conduction disturbance (superclass)",
                        "SUPER_HYP": "hypertrophy (superclass)"}.get(n, m["description"])
                out.append(f"| {n} | {desc} | {m['support']} | {_num(m['auc'], nd=3)} | {_pct(m['sensitivity'])} | "
                           f"{_pct(m['specificity'])} | {_pct(m['ppv'])} |")
        c = st["calibration"]
        out += ["", f"Calibration (one temperature, fitted on validation): T = {c['temperature']:.2f}; test ECE "
                f"{_pct(c['ece_before'])} → {_pct(c['ece_after'])} (all statements pooled).", "",
                "Subgroups (test fold, superclass macro-AUC): " + "; ".join(
                    f"{g} {v['superclass_macro_auc']:.3f} (n={v['n']})" for g, v in st["subgroups"].items()) + ".", ""]
    if me:
        out += [f"### 7.2 Interval measurements (signal processing) — adopted version {ADOPTED_MEASURE}", "",
                "Median beat per lead → QRS onset/offset from the 12-lead spatial velocity (QRS core, then out to a threshold "
                "or the first velocity minimum) → T end where the 12-lead RMS returns to baseline (capped 30 ms after the "
                "tangent-method T end) → P wave searched up to 300 ms before the QRS. Thresholds tuned on "
                + (f"{tu['n_records']:,} training-fold ECGs" if tu else "training folds") + " against GE 12SL. "
                f"Test fold: {me['n_records']:,} ECGs, {me['failed']} not measurable, {1000 * me['seconds_per_ecg']:.0f} ms per ECG on one CPU core.", "",
                "**No ground truth exists here.** PTB-XL+ supplies the measurements of two commercial algorithms (GE 12SL, Uni-G). "
                "The useful yardstick is how closely the two commercial algorithms agree with each other.", "",
                "| Measurement | Ours − 12SL: mean ± SD | Ours − Uni-G: mean ± SD | 12SL − Uni-G: mean ± SD | Ours within tolerance of 12SL | 12SL within tolerance of Uni-G | n |",
                "|---|---|---|---|---:|---:|---:|"]
        ag = me["agreement"]
        for k, (name, unit) in ECG12_MEASURE_NAMES.items():
            a, b, c = ag["vs_12sl"].get(k), ag["vs_unig"].get(k), ag["12sl_vs_unig"].get(k)
            if not a:
                continue
            f = lambda m: "—" if not m else f"{m['mean_diff']:+.1f} ± {m['sd_diff']:.1f} {unit}"  # noqa: E731
            tol = f" (±{a['within']} {unit})"
            out.append(f"| {name}{tol} | {f(a)} | {f(b)} | {f(c)} | {_pct(a['share_within'])} | "
                       f"{_pct(c['share_within']) if c else '—'} | {a['n']:,} |")
        iec = me["iec_orientation_ms"]
        out += ["", "For orientation only, IEC 60601-2-25 accepts mean difference / SD up to "
                + ", ".join(f"{ECG12_MEASURE_NAMES[k][0]} ±{v[0]} / {v[1]} ms" for k, v in iec.items())
                + " — but against the CSE referee on the CSE database, which we do not have yet (it must be licensed).",
                f"PR is reported only when a P wave is found and the rhythm is regular: {me['pr_reported_where_12sl_reports']:,} test ECGs.", "",
                "Versions (ours − 12SL, mean ± SD; v0.2 was chosen over v0.1 on validation fold 9, then scored on test once):", "",
                "| Version | Fold | QRS (ms) | PR (ms) | QT (ms) |", "|---|---|---|---|---|"]
        for v in ("v0.1", "v0.2"):
            for split in ("val", "test"):
                r = _load(f"ecg12_measurements_{split}_{v}")
                if r:
                    a = r["agreement"]["vs_12sl"]
                    out.append(f"| {v} | {split} | " + " | ".join(f"{a[k]['mean_diff']:+.1f} ± {a[k]['sd_diff']:.1f}" for k in ("qrs_ms", "pr_ms", "qt_ms")) + " |")
        out += ["", "The v0.1 test result prompted the work on v0.2; its causes were diagnosed on training ECGs and the "
                "fix chosen on validation. v0.1 had large misses in wide-QRS ECGs (QRS end ran into the ST segment), low or slowly rising P waves "
                "(P onset too early) and flat T waves (T end drifted late); v0.2 adds a rule for each.", ""]
    ex = _load("ecg12_external_chapman_v0.1")
    if ex:
        out += ["### 7.3 External test — Chapman–Shaoxing (China, GE MUSE, 2013–2018)", "",
                f"All {ex['n_records']:,} ECGs, one per patient, never used for any choice. Different country, years and ECG "
                "system from PTB-XL. Physician labels mapped to our statements by a fixed table "
                "(`data/chapman.py`); condition labels are not exhaustive, so specificity and PPV are lower bounds.", "",
                "| Statement | ECGs with it | AUC | Sensitivity | Specificity | PPV |", "|---|---:|---:|---:|---:|---:|"]
        for k, v in sorted(ex["per_label"].items(), key=lambda kv: -kv[1]["support"]):
            out.append(f"| {k} ({v['description']}) | {v['support']:,} | {v['auc']:.3f} | {_pct(v['sensitivity'])} | "
                       f"{_pct(v['specificity'])} | {_pct(v['ppv'])} |")
        sg = ex["subgroups"]
        mm = ex["measurements"]
        out += ["", "NORM here is a proxy (sinus rhythm with no other label), so its numbers are only indicative. "
                f"AF AUC by sex: women {sg['female']['afib_auc']:.3f}, men {sg['male']['afib_auc']:.3f}.", "",
                "**Ranking transfers, thresholds do not always.** AUCs stay high, but the yes/no thresholds chosen on PTB-XL "
                "miss many Chapman bradycardias (SBRAD AUC 0.965, sensitivity 12%) and almost all atrial flutter. Thresholds "
                "are an operating point to set per site on local validation data, not a property of the model.", "",
                f"Measurements against **GE MUSE** (third commercial reference; {mm['failed']} ECG not measurable, "
                f"{1000 * mm['seconds_per_ecg']:.0f} ms per ECG):", "",
                "| Measurement | Ours − MUSE: mean ± SD | Within tolerance | n |", "|---|---|---:|---:|"]
        for k, (name, unit) in ECG12_MEASURE_NAMES.items():
            a = mm["vs_muse"].get(k)
            if a:
                out.append(f"| {name} (±{a['within']} {unit}) | {a['mean_diff']:+.1f} ± {a['sd_diff']:.1f} {unit} | {_pct(a['share_within'])} | {a['n']:,} |")
        out += ["", "MUSE publishes no PR interval in this dataset. MUSE heart rate is the ventricular rate; ours is the mean RR, "
                "which explains most of the heart-rate spread in atrial fibrillation.", ""]
    ru = _load("ecg12_rules_v0.1")
    if ru:
        out += ["### 7.4 Rate and interval statements: measurement rules vs the learned model", "",
                "Rules with fixed clinical cut-offs on our own measurements (`ecg12/rules.py`): "
                + "; ".join(f"{k}: {v}" for k, v in ru["rules"].items()) + ". " + ru["selection_rule"], "",
                "| Statement | Data | Model F1 | Rule F1 | Rule sensitivity | Rule PPV |", "|---|---|---:|---:|---:|---:|"]
        names = {"ptbxl_val": "PTB-XL validation", "ptbxl_test": "PTB-XL test", "chapman_external": "Chapman (external)"}
        for k in ru["rules"]:
            for split, d in ru["results"].items():
                v = d[k]
                out.append(f"| {k} | {names[split]} | {v['model']['f1']:.2f} | {v['rule']['f1']:.2f} | "
                           f"{_pct(v['rule']['sensitivity'])} | {_pct(v['rule']['ppv'])} |")
        out += ["", "Decision (validation): " + ", ".join(f"{k} → {v}" for k, v in ru["chosen"].items()) + ".", "",
                "**Finding: hospitals write these statements differently.** Chapman's physicians label sinus bradycardia "
                "by the definition (rule F1 0.96 there); PTB-XL's cardiologists mostly do not label 55–59 bpm (rule PPV 16%). "
                "No single model or rule matches both. In the product these statements must follow the **site's own "
                "convention**, chosen and verified on that hospital's data during installation. Long QT is labelled far "
                "less often than QTc ≥ 460 ms occurs in both datasets.", ""]
    v2 = _load("ecg12_statements_v0.2")
    sel = _load("ecg12_selection")
    if v2 and sel:
        af = _load("ecg12_ningbo_af_check")
        out += ["### 7.5 More data: v0.2 adds the Ningbo part of Chapman–Shaoxing–Ningbo (China)", "",
                f"v0.2 is trained on PTB-XL folds 1–8 plus {_ningbo_train_n(v2)} ECGs from the Ningbo part (80% patient-level "
                "training split; 10% validation, 10% test). "
                "The 10,646 Chapman–Shaoxing ECGs inside that database were excluded (46 of 46 sampled ECGs match "
                "Chapman signal-for-signal), so Chapman stays a held-out test. Loss is masked: Ningbo ECGs teach only the "
                "statements their labels map to without ambiguity.", ""]
        if af:
            g = af["groups"]
            out += ["**Ningbo atrial-fibrillation labels are not trusted.** The Ningbo part has no fibrillation code and "
                    f"{af['ningbo_part_counts']['AFLT code 164890007']:,} 'flutter' ECGs (22%). On the signals they behave like "
                    f"fibrillation: irregular RR in {_pct(g['Ningbo AFLT (as coded)']['rr_irregular_share'])} (Chapman fibrillation "
                    f"{_pct(g['Chapman AFIB']['rr_irregular_share'])}, Chapman flutter {_pct(g['Chapman AFLT']['rr_irregular_share'])}). "
                    "Neither label is used.", ""]
        out += [f"Selection rule: {sel['rule']}", "",
                "| | PTB-XL validation, all statements | Ningbo validation, mapped statements |", "|---|---:|---:|"]
        for v in (sel["baseline"], sel["candidate"]):
            out.append(f"| {v} | {sel['ptbxl_val_all'][v]:.3f} | {sel['ningbo_val_mapped'][v]:.3f} |")
        out += ["", f"**Chosen: {sel['chosen']}.**", "",
                "Test results (each scored once):", "",
                "| Test set | v0.1 | v0.2 |", "|---|---:|---:|"]
        v1 = _load("ecg12_statements_v0.1")
        for k in ("superclass", "diagnostic", "form", "rhythm", "all"):
            out.append(f"| PTB-XL fold 10, {k} macro-AUC | {v1['test'][k]['macro_auc']:.3f} | {v2['test'][k]['macro_auc']:.3f} |")
        out.append(f"| Ningbo test split, mapped statements macro-AUC | — | {v2['ningbo']['test']['macro_auc_mapped']:.3f} |")
        e1, e2 = _load("ecg12_external_chapman_v0.1"), _load("ecg12_external_chapman_v0.2")
        if e1 and e2:
            out += ["", "Chapman–Shaoxing (held out; same country and ECG system as Ningbo, so no longer fully independent for v0.2):", "",
                    "| Statement | ECGs | v0.1 AUC | v0.2 AUC | v0.1 sensitivity | v0.2 sensitivity |", "|---|---:|---:|---:|---:|---:|"]
            for k, a1 in sorted(e1["per_label"].items(), key=lambda kv: -kv[1]["support"]):
                a2 = e2["per_label"].get(k)
                if a2:
                    out.append(f"| {k} | {a1['support']:,} | {a1['auc']:.3f} | {a2['auc']:.3f} | {_pct(a1['sensitivity'])} | {_pct(a2['sensitivity'])} |")
        sg = v2["subgroups"]
        out += ["", "v0.2 subgroups (PTB-XL test, superclass macro-AUC): " + "; ".join(
            f"{g} {v['superclass_macro_auc']:.3f}" for g, v in sg.items()) + ".", ""]
    return out


def write_results() -> str:
    out = ["# Cardiotic AI — research results", "",
           "Generated by `python -m cardiotic_ml.cli report` from the JSON files in this folder.",
           "All numbers are from **public research datasets** and **patients the model never saw in training**.",
           "They are research results, not clinical performance claims.", ""]

    q = _load("qrs_detection")
    if q:
        out += ["## 1. Heartbeat (QRS) detection — MIT-BIH, all 48 records", "",
                f"Protocol: {q['protocol']}.", "",
                "| Detector | Se (48 records) | +P (48 records) | Se (44 non-paced) | +P (44 non-paced) | Missed | False |",
                "|---|---:|---:|---:|---:|---:|---:|"]
        for name, m in q["methods"].items():
            a, b = m["all_48"], m["non_paced_44"]
            out.append(f"| {name} | {_pct(a['sensitivity'])} | {_pct(a['ppv'])} | {_pct(b['sensitivity'])} | {_pct(b['ppv'])} | {a['fn']:,} | {a['fp']:,} |")
        best = max(q["methods"].items(), key=lambda kv: kv[1]["all_48"]["sensitivity"] + kv[1]["all_48"]["ppv"])
        worst = sorted(best[1]["per_record"], key=lambda r: r["sensitivity"] + r["ppv"])[:5]
        out += ["", f"Hardest records for `{best[0]}`: " + ", ".join(
            f"{r['record']} (Se {_pct(r['sensitivity'])}, +P {_pct(r['ppv'])})" for r in worst), ""]

    qvers = [(v, _load(f"signal_quality_{v}")) for v in ("v0.1", "v0.2", "v0.3")]
    qvers = [(v, r) for v, r in qvers if r]
    if qvers:
        from cardiotic_ml.pipeline import QUALITY_MODEL
        adopted_q = QUALITY_MODEL.removeprefix("quality_net_")
        out += ["## 2. Signal-quality model (AI model #1)", "",
                "Synthetic test: 10,000 windows from the 22 DS2 patients, noise from a part of the noise recordings never "
                "used in training. Real-data check: CinC 2017 recordings labelled by experts (normal, AF, other rhythm, and "
                "'too noisy to classify'), plus MIT-BIH DS2 records with AF or flutter.", "",
                "| Version | Recipe | Synthetic test accuracy | Unusable caught (Se) | CinC AF windows rated unusable | CinC 'too noisy' windows rated noisy or unusable | MIT-BIH 222 windows rated unusable |",
                "|---|---|---:|---:|---:|---:|---:|"]
        for v, r in qvers:
            real = r.get("real_data_test", {})
            af, nz, m222 = real.get("cinc_A", {}), real.get("cinc_~", {}), real.get("mitdb_222", {})
            noisy_or_bad = (nz.get("noisy", 0) + nz.get("unusable", 0)) if nz else None
            out.append(f"| {v}{' (adopted)' if v == adopted_q else ''} | {r['model_card'].get('recipe', {})} | {_pct(r['test']['accuracy'])} | "
                       f"{_pct(r['test']['per_class']['unusable']['sensitivity'])} | {_pct(af.get('unusable'))} | {_pct(noisy_or_bad)} | {_pct(m222.get('unusable'))} |")
        v, s = next((v, r) for v, r in qvers if v == adopted_q)
        rep = s["test"]
        out += ["", f"**Adopted: {v}.** Synthetic-test detail:", ""]
        out += _class_table(rep) + [""] + _confusion(rep) + [""]
        if s.get("real_data_test"):
            out += ["Real-data check (test split), share of 2.5 s windows rated:", "",
                    "| Recording type | Windows | good | noisy | unusable |", "|---|---:|---:|---:|---:|"]
            for k, m in s["real_data_test"].items():
                out.append(f"| {k} | {m.get('windows', '—') if isinstance(m.get('windows'), int) else '—'} | "
                           f"{_pct(m['good'])} | {_pct(m['noisy'])} | {_pct(m['unusable'])} |")
            out.append("")
        out += ["Synthetic labels are proxies derived from the injected noise level (see `quality/dataset.py`). "
                "The CinC 'too noisy' label is for the whole recording, so not every window in such a recording is bad.", ""]

    versions = [(v, _load(f"beat_classification_{v}")) for v in ("v0.1", "v0.2")]
    versions = [(v, r) for v, r in versions if r]
    if versions:
        out += ["## 3. Beat classifier (AI model #2)", "",
                "Inter-patient protocol (de Chazal): trained on DS1, model selected on 4 held-out DS1 patients, "
                f"tested once on the 22 DS2 patients ({sum(versions[0][1]['sizes']['test']):,} beats).", "",
                "| Version | Recipe | Val macro-F1 | Test accuracy | N Se / +P | S Se / +P | V Se / +P | F Se / +P |",
                "|---|---|---:|---:|---:|---:|---:|---:|"]
        for v, r in versions:
            pc = r["test"]["per_class"]
            cell = lambda c: f"{_pct(pc[c]['sensitivity'])} / {_pct(pc[c]['ppv'])}"
            out.append(f"| {v} | {r['model_card'].get('recipe', {})} | {_pct(r['training']['best_val_macro_f1'])} | "
                       f"{_pct(r['test']['accuracy'])} | {cell('N')} | {cell('S')} | {cell('V')} | {cell('F')} |")
        from cardiotic_ml.pipeline import BEAT_MODEL
        adopted = BEAT_MODEL.removeprefix("beat_net_")
        v, b = next((v, r) for v, r in versions if v == adopted)
        rep = b["test"]
        out += ["", f"**Adopted: {v}** (best on the validation patients). Detail:", ""]
        out += _class_table(rep) + [""] + _confusion(rep) + ["",
                "N = normal or bundle-branch beats · S = supraventricular ectopic · V = ventricular ectopic · F = fusion. "
                "In this protocol S and F are known to be hard (few training examples, S beats often look normal). "
                "Accuracy is dominated by N and is not the number to judge the model by: read Se and +P for S and V.", ""]
    rvers = [(v, _load(f"rhythm_classification_{v}")) for v in ("v0.1", "v0.2", "v0.4", "v0.5")]
    rvers = [(v, r) for v, r in rvers if r]
    rh = None
    if rvers:
        from cardiotic_ml.pipeline import RHYTHM_MODEL
        adopted_r = RHYTHM_MODEL.removeprefix("rhythm_net_")
        out += ["## 4. Rhythm classifier (AI model #3)", "",
                "Trained on CinC 2017 handheld single-lead ECGs, tested on held-out CinC records (stratified by record; "
                "the dataset has no patient IDs) and on MIT-BIH Holter recordings. Record-level CinC score = average of 30 s "
                "windows; challenge F1 = mean F1 of normal, AF and other rhythm. The best 2017 challenge entries scored about "
                "83% on their hidden test set (not directly comparable).", "",
                "MIT-BIH split for rhythm work: **validation** records 201, 215, 207, 209, 220 (used only to choose versions); "
                "**test** = the 22 DS2 records, never used for training by any version. v0.2 also trains on 17 other DS1 records.", "",
                "| Version | Recipe | CinC val F1 | CinC test F1 | MIT-BIH val: AF found · false-AF windows | MIT-BIH test (DS2): AF Se · false-AF windows · AF PPV · specificity | AFDB val: AF Se · false-AF windows | AFDB test: AF Se · false-AF windows · AF PPV · specificity |",
                "|---|---|---:|---:|---:|---:|---:|---:|"]
        g = _load("rhythm_gate_v0.3")
        rows = list(rvers)
        if g and _load("rhythm_mitdb_test_v0.3"):
            base = dict(rvers)["v0.1"]
            rows.append(("v0.3", {"model_card": {"recipe": f"v0.1 + ectopy gate {g['chosen']} (CinC = v0.1: gate off for lead I)"},
                                  "val_challenge_f1": base.get("val_challenge_f1"), "test_challenge_f1": base["test_challenge_f1"]}))
        for v, r in rows:
            mv, mt = _load(f"rhythm_mitdb_val_{v}"), _load(f"rhythm_mitdb_test_{v}")
            mv_s = f"{int(mv['windows_af'] * mv['af_sensitivity'] + 0.5)}/{int(mv['windows_af'])} · {int(mv['false_af_windows'])}" if mv else "—"
            mt_s = (f"{_pct(mt['af_sensitivity'])} · {int(mt['false_af_windows'])} · {_pct(mt['af_ppv'])} · {_pct(mt['af_specificity'])}"
                    if mt else "—")
            av, at = _load(f"rhythm_afdb_val_{v}"), _load(f"rhythm_afdb_test_{v}")
            av_s = f"{_pct(av['af_sensitivity'])} · {int(av['false_af_windows']):,}" if av else "—"
            at_s = (f"{_pct(at['af_sensitivity'])} · {int(at['false_af_windows']):,} · {_pct(at['af_ppv'])} · {_pct(at['af_specificity'])}"
                    if at else "—")
            out.append(f"| {v}{' (adopted)' if v == adopted_r else ''} | {r['model_card'].get('recipe', {})} | "
                       f"{_pct(r.get('val_challenge_f1'))} | {_pct(r['test_challenge_f1'])} | {mv_s} | {mt_s} | {av_s} | {at_s} |")
        out += ["", "**What happened with the AF false-alarm fix (issue 5):**", "",
                "- **v0.2** (ectopy-aware features + MIT-BIH training windows) passed every validation check (false-AF windows "
                "38 → 3, no AF lost), and on the unseen DS2 patients cut false-AF windows 106 → 25. But it found AF in only 77% of "
                "AF windows (v0.1: 97%), missing most of record 221 (AF with frequent PVCs: 18 of 50 windows). It learned a shortcut, "
                "\"many PVCs means not AF\", from 624 PVC-rich training windows that contained no AF. **Not adopted.**",
                "- **v0.3** (v0.1 + an ectopy gate: an AF call is withdrawn when the rhythm becomes regular once PVC-adjacent beats "
                "are removed; gate only on lead MLII/II, where the beat classifier is validated) cut validation false AF 38 → 6 with no "
                "AF lost, but on DS2 found AF in only 65% of AF windows. AF irregularity varies a lot between patients (PVC-free RR "
                "variation median 0.22 in validation patient 201, 0.14 in test patient 210), and a threshold chosen on one AF patient "
                "does not transfer. **Not adopted.**",
                "- **Pipeline keeps v0.1**: it catches ~97% of AF but raises more false alarms, which go to a reader for review. "
                "Missing AF is the more harmful error for this product.",
                "- **Lessons:** the validation set had a single AF patient, too few to choose anything that trades AF sensitivity; "
                "and DS2 has now informed two decisions, so it is no longer an unbiased final test. Both are fixed by an AF validation "
                "set with many AF patients (MIT-BIH AF Database, 23 patients) and a fresh external test set.", ""]
        sel = _load("rhythm_selection")
        if sel:
            out += ["**Retry with the MIT-BIH AF Database** (23 Holter patients, ~10 h each): patients ranked by AF burden "
                    "and dealt into train 8 / validation 8 / test 7. The AFDB test patients were not used for any decision.", "",
                    f"Selection rule (fixed before any AFDB result): {sel['rule']}", "",
                    "| Candidate | Passes | AFDB-val AF Se drop | MIT-BIH-val AF Se drop | Worst AFDB-val patient drop | CinC val F1 drop | False-AF windows (val) vs v0.1 |",
                    "|---|---|---:|---:|---:|---:|---:|"]
            for c in sel["candidates"]:
                out.append(f"| {c['version']} | {'yes' if c['passes'] else 'no'} | {_pct(c['afdb_af_se_drop'])} | {_pct(c['mitdb_af_se_drop'])} | "
                           f"{_pct(c['worst_patient_af_se_drop'])} | {_pct(c['cinc_val_f1_drop'])} | {c['false_af']} vs {c['false_af_baseline']} |")
            out += ["", f"**Chosen by the rule: {sel['chosen']}.** Neither candidate passed. v0.4 halved validation false-AF "
                    "windows (200 → 100) and kept every MIT-BIH AF window, but lost 4.2 points of AF sensitivity on AFDB "
                    "validation, 16 points in patient 07859 — fast (~100 bpm), unusually regular AF (RR variation 0.12) where the "
                    "windows it dropped had twice the 'PVC' share (4.1% vs 2.1%). In AF the beat classifier's PVC labels are "
                    "partly AF beats it misreads, so features built on them stay fragile. This time the validation rule caught the "
                    "problem, so the AFDB test patients were used only once, for the chosen model; v0.4 and v0.5 were never run "
                    "on them, which keeps them clean for future attempts.", ""]
            at = _load(f"rhythm_afdb_test_{adopted_r}")
            if at:
                out += [f"AFDB test patients, {adopted_r} (fresh data):", "",
                        "| Patient | AF windows | AF detected | Non-AF windows | False AF windows |", "|---|---:|---:|---:|---:|"]
                out += [f"| {p['record']} | {p['af_windows']} | {p['af_detected']} | {p['non_af_windows']} | {p['false_af_windows']} |"
                        for p in at["per_record"]]
                out.append("")
        v, rh = next((v, r) for v, r in rvers if v == adopted_r)
        rep = rh["test"]
        out += [f"**Adopted: {v}.** CinC test detail:", ""]
        out += _class_table(rep) + [""] + _confusion(rep) + ["", "N normal sinus · A atrial fibrillation · O other rhythm · ~ too noisy to classify.", ""]
        x = _load(f"rhythm_mitdb_test_{v}")
        if x:
            out += [f"MIT-BIH test (DS2) detail for {v}. {x['protocol']}.", "",
                    f"- AF windows: {int(x['windows_af']):,} · non-AF windows: {int(x['windows_non_af']):,}",
                    "- What the model said on non-AF windows: " + ", ".join(f"{k} {int(n):,}" for k, n in x["predictions_on_non_af_windows"].items()), "",
                    "| Record | AF windows | AF detected | False AF windows |", "|---|---:|---:|---:|"]
            out += [f"| {r['record']} | {int(r['af_windows'])} | {int(r['af_detected'])} | {int(r['false_af_windows'])} |" for r in x["per_record"]]
            out.append("")
    cb = _load("beat_calibration")
    if rh or cb:
        out += ["## 5. Confidence calibration (M5)", "",
                "Temperature scaling fitted on validation data only. ECE = expected calibration error "
                "(gap between stated confidence and observed accuracy; lower is better).", "",
                "| Model | Temperature | Test ECE before | Test ECE after | 'High' share / accuracy | 'Moderate' share / accuracy | 'Low' share / accuracy |",
                "|---|---:|---:|---:|---:|---:|---:|"]
        def lv(d, k):
            return f"{_pct(d[k]['share'])} / {_pct(d[k]['accuracy'])}"
        if rh:
            c = rh["calibration"]
            out.append(f"| rhythm_net {rh['version'] if 'version' in rh else 'v0.1'} (records) | {c['temperature']:.2f} | {_pct(c['ece_before'])} | {_pct(c['ece_after'])} | "
                       f"{lv(c['confidence_levels'], 'high')} | {lv(c['confidence_levels'], 'moderate')} | {lv(c['confidence_levels'], 'low')} |")
        if cb:
            c = cb["confidence_levels_after"]
            out.append(f"| {cb['beat_model']} (beats) | {cb['temperature']:.2f} | {_pct(cb['ece_before'])} | {_pct(cb['ece_after'])} | "
                       f"{lv(c, 'high')} | {lv(c, 'moderate')} | {lv(c, 'low')} |")
        out.append("")

    e = _load("end_to_end_pipeline")
    if e:
        rep, t = e["test"], e["totals"]
        ref_total = t["matched"] + t["missed"] + t["in_unusable_segments"]
        out += ["## 6. End to end — the whole pipeline on 22 unseen patients", "",
                f"Quality gate `{e.get('quality_model', 'quality_net_v0.1')}` → `{e['qrs_method']}` detection → R-peak refinement → `{e['beat_model']}`, run on the full "
                "30-minute DS2 recordings and scored against the cardiologists' annotations. This is what a user would get.", "",
                f"- Reference beats: {ref_total:,} · matched to a detection: {t['matched']:,} ({_pct(t['matched'] / ref_total)}) · "
                f"missed by the detector: {t['missed']:,} · inside segments the quality gate marked unusable: {t['in_unusable_segments']:,} · "
                f"extra detections with no reference beat: {t['unmatched_detections']:,}",
                f"- Classification of matched beats: accuracy **{_pct(rep['accuracy'])}**, macro-F1 **{_pct(rep['macro_f1'])}**", ""]
        out += _class_table(rep) + [""]
    out += _ecg12_section()
    out += ["## 8. Issues found while testing", "",
            "### Fixed",
            "1. **Beat positions ~40 ms late.** Pan-Tompkins marks beats after the R peak; the classifier is trained on "
            "R-peak positions. The first end-to-end run agreed with the cardiologists on only 42% of beats in a test minute. "
            "Every detection is now refined to the R peak (`qrs.refine_peaks`): 92% on the same minute. Regression test added.",
            "2. **Quality gate hid arrhythmic, low-amplitude signal.** With quality v0.1, record 222 (R amplitude 0.68 mV against a "
            "1.45 mV median; flutter, AF and nodal-rhythm episodes) had ~half its windows rated unusable, and 8–16% of clean "
            "expert-labelled handheld ECG windows were rated unusable. v0.2 (AF/other-rhythm windows as good, low-amplitude "
            "examples) fixed that but became lenient on real noisy recordings; v0.3 adds real noisy windows. Chosen on validation: "
            "beats hidden in unusable segments across the 22 test patients fell from 1,839 to about 250, record 222 from 1,173 to about 70.",
            "3. **False beat at the start of every recording.** Pan-Tompkins' thresholds are still settling in the first moments "
            "(record 221: detection at 0.32 s, first real beat at 0.61 s). Detections in the first 0.4 s are now dropped. Test added.",
            "4. **'Supraventricular ectopic beats' reported during AF.** Premature atrial beats are not defined in AF; that finding "
            "is now suppressed when AF is the predominant rhythm.",
            "5. **Resampling mixed up the leads of a 12-lead ECG.** The resampling helper worked along the first array axis, so "
            "a (12 leads × samples) ECG was resampled across leads instead of over time. Found by the first 12-lead end-to-end run "
            "(training was not affected: it uses the database's own 100 Hz files). It now always works along time; single-lead "
            "results are unchanged (demo record 233 reproduced exactly). Test added.",
            "6. **12-lead measurements were reported for pure noise.** When every lead is rated unusable, measurements and "
            "statements are now both withheld. Test added.",
            "7. **12-lead measurement v0.1 had large misses** (wide QRS, low P waves, flat T waves; section 7.2). Fixed in v0.2.", "",
            "### Open (next work)",
            "8. **AF over-called in ectopy-rich recordings — four candidates tried, none adopted** (section 4). Every candidate "
            "cut false AF substantially but lost real AF in some patient. With the MIT-BIH AF Database (8 validation AF patients) "
            "the pre-declared rule now catches this on validation. On fresh AFDB test patients, v0.1 itself finds 97.4% of AF "
            "windows with 95.5% positive predictivity, so the false-alarm problem is concentrated in non-AF patients with frequent "
            "ectopy (MIT-BIH DS2: PPV ~60%). Next options: (a) an explicit AF-probability operating point chosen on validation per "
            "use case (screening vs. review) — a transparent sensitivity/false-alarm trade-off; (b) more AF data (Long-Term AF "
            "Database, 84 patients); (c) beat labels inside AF for a beat classifier that is reliable during AF.",
            "8b. **The beat classifier labels some AF beats as ventricular**, on handheld lead I especially (a quarter of CinC AF "
            "windows had ≥10% 'PVCs'). Anything built on its PVC labels must be restricted to leads where it is validated.",
            "9. **Supraventricular (S) and fusion (F) beats are weak** (S Se ~30%, F ~0%). The v0.2 augmentation recipe scored lower "
            "on validation and was not adopted. Next: more S/F data (INCART, long-term AF database), patient-adaptive RR features.",
            "10. **Beat-model calibration does not transfer across patients.** A temperature fitted on the 4 validation patients "
            "made test ECE worse (slightly under-confident). The rhythm model's calibration did improve on test. Next: calibrate "
            "beats on a larger, more varied patient set; until then beat confidence levels must not be shown as calibrated in any UI.",
            "11. **Proxy and weak labels.** Synthetic quality labels come from known noise levels; CinC 'too noisy' labels are per "
            "recording, not per window. Clinician-labelled windows are needed.",
            "12. **Public data only.** MIT-BIH (1970s Holter, MLII) and CinC 2017 (handheld, lead I). Performance on modern 12-lead "
            "carts and OT/ICU monitors is unknown until tested on partner-hospital data.",
            "13. **CinC split is by record, not patient** (no patient IDs are published), so some test records may share a patient "
            "with training records. The cross-dataset MIT-BIH result is the stronger generalisation evidence.",
            "14. **Rare 12-lead statements are weak.** Wolff-Parkinson-White (8 test ECGs), long QT (11), atrial flutter (7) and "
            "anterior MI (35) have low sensitivity at thresholds chosen from very few validation examples. Next: more 12-lead data "
            "(CODE-15%, MIMIC-IV-ECG; licences in PRODUCT_PLAN §7) and, for long QT, a rule on our own measured QTc instead of "
            "the learned statement.",
            "15. **Sex gap in the 12-lead model.** Superclass macro-AUC is 0.914 for women and 0.935 for men on the test fold. "
            "Needs investigation (sex-specific criteria such as LVH voltage, class balance) before any claim; subgroup results "
            "must be part of every future model card.",
            "16. **12-lead measurements are checked against other algorithms, not a referee.** IEC 60601-2-25 requires the CSE "
            "database (licensed). PR is not measured beyond 300 ms (very long first-degree AV block) and paced ECGs are not "
            "handled specially.",
            "17. **The signal-quality model was trained on Holter lead II, not 12-lead ECGs.** On clean PTB-XL validation ECGs "
            "it rates 0.35% of leads unusable (about 1 ECG in 25 gets an 'unusable lead' note) and 20% noisy. Next: train it on "
            "12-lead data, e.g. using PTB-XL's own noise and electrode annotations.",
            "18. **PTB-XL is one manufacturer and one country** (Schiller devices, Germany, 1989–1996). Performance on today's ECG "
            "carts in Indian and US hospitals is unknown until tested on partner data.", ""]
    path = REPORTS_DIR / "RESULTS.md"
    path.write_text("\n".join(out))
    return str(path)
