"""Draft a per-site operating-point file from the site's own cardiologist-labelled ECGs (installation step).

    cardiotic-engine site-config --dir ecgs/ --labels labels.csv --site-id HOSPITAL-1 --out site_config.json

labels.csv: one row per ECG file, `file,statements` with SCP-ECG codes separated by ';' (empty = no statement).
A statement counts as *labelled* by the site when it appears in the file at least once (override with --labelled).
The result is a DRAFT: `approved_by` and `approved_at` are empty, and the engine refuses it until the site's
cardiology lead has reviewed the report next to it and filled both in.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np


def draft(directory: str | Path, labels_csv: str | Path, site_id: str, config_version: str = "1", policy: str = "max_f1",
          target: float = 0.9, min_positives: int | None = None, labelled: list[str] | None = None, engine=None) -> tuple[dict, dict]:
    from cardiotic_ml.ecg12 import analyze, site

    from cardiotic_engine.api import LEADS, Engine, InputError

    eng = engine or Engine()
    card = eng._m.manifest["models"]["ecg12"]
    names = card["labels"]
    rows = list(csv.DictReader(open(labels_csv, newline="")))
    if not rows or "file" not in rows[0] or "statements" not in rows[0]:
        raise ValueError("labels file needs the columns: file,statements")
    y, p, used, skipped = [], [], [], []
    for r in rows:
        codes = {c.strip() for c in (r["statements"] or "").split(";") if c.strip()}
        bad = codes - set(names)
        if bad:
            raise ValueError(f"{r['file']}: unknown statements {sorted(bad)} (the model knows: {len(names)} statements; see ml/reports)")
        try:
            ecg = eng.read_file((Path(directory) / r["file"]).read_bytes())
            if not ({"I", "II"} <= set(ecg.leads) and set(LEADS[6:]) <= set(ecg.leads)):
                raise InputError("not a 12-lead ECG")
            leads = dict(ecg.leads)
            i, ii = leads["I"], leads["II"]
            for k, v in {"III": ii - i, "AVR": -(i + ii) / 2, "AVL": i - ii / 2, "AVF": ii - i / 2}.items():
                leads.setdefault(k, v)
            x = np.stack([leads[l] for l in LEADS]).astype(np.float32)[:, : int(10 * ecg.fs)]
            p.append(analyze.probabilities(x, ecg.fs, eng._m.ecg12))
        except (InputError, OSError) as e:
            skipped.append({"file": r["file"], "reason": str(e)})
            continue
        y.append([n in codes for n in names])
        used.append(r["file"])
    if len(used) < 2:
        raise ValueError(f"only {len(used)} usable ECGs; a site needs hundreds of labelled ECGs (skipped: {skipped[:3]})")
    y, p = np.array(y, dtype=np.float32), np.array(p)
    lab = set(labelled) if labelled else {n for j, n in enumerate(names) if y[:, j].sum() > 0}
    unknown = np.array([[n not in lab for n in names]] * len(y), dtype=np.float32)
    chosen = site.choose(y, p, names, card["thresholds"], policy=policy, target=target, unknown=unknown,
                         **({"min_positives": min_positives} if min_positives is not None else {}))
    config = {"site_id": site_id, "config_version": config_version, "model": f"{card['name']}_{card['version']}",
              "approved_by": "", "approved_at": "", "statements": {k: v for k, v in chosen.items() if v["source"] == "site"}}
    report = {"ecgs_used": len(used), "skipped": skipped, "policy": policy, "labelled_statements": sorted(lab),
              "statements": {k: v for k, v in chosen.items()}, "note": "DRAFT. The cardiology lead reviews this report and fills in approved_by and approved_at; the engine refuses the file until then."}
    return config, report


def write(config: dict, report: dict, out: str | Path) -> None:
    out = Path(out)
    out.write_text(json.dumps(config, indent=1))
    out.with_suffix(".report.json").write_text(json.dumps(report, indent=1, default=float))
