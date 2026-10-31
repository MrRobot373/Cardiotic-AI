import csv
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import ingest_writers as w  # noqa: E402

from cardiotic_engine import siteconfig  # noqa: E402
from cardiotic_engine.api import Engine, SiteConfigError  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def test_site_config_draft_is_unsigned_then_loads_once_approved(tmp_path):
    x = np.load(FIX / "fixtures.npz")["ecg12"]
    eng = Engine()
    rows = []
    for i in range(8):  # eight scaled copies stand in for a site's labelled ECGs
        (tmp_path / f"e{i}.csv").write_bytes(w.csv_file(x * (0.8 + 0.05 * i), 500))
        rows.append((f"e{i}.csv", "AFIB;PVC" if i % 2 == 0 else "SR"))
    rows.append(("broken.csv", ""))
    (tmp_path / "broken.csv").write_text("not,an,ecg\n1,2,3\n")
    with open(tmp_path / "labels.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["file", "statements"])
        wr.writerows(rows)
    cfg, rep = siteconfig.draft(tmp_path, tmp_path / "labels.csv", "test-site", min_positives=2, engine=eng)
    assert rep["ecgs_used"] == 8 and rep["skipped"][0]["file"] == "broken.csv"
    assert {"AFIB", "PVC", "SR"} <= set(rep["labelled_statements"]) and set(cfg["statements"]) <= {"AFIB", "PVC", "SR"}
    assert cfg["approved_by"] == "" and cfg["model"] == "ecg12_net_v0.3"
    siteconfig.write(cfg, rep, tmp_path / "site.json")
    with pytest.raises(SiteConfigError, match="missing"):
        Engine(site_config=tmp_path / "site.json")  # a draft nobody approved is refused
    import json
    cfg["approved_by"], cfg["approved_at"] = "Cardiology lead", "2026-10-30"
    (tmp_path / "approved.json").write_text(json.dumps(cfg))
    assert Engine(site_config=tmp_path / "approved.json").info()["site_config"]["site_id"] == "test-site"


def test_site_config_refuses_unknown_statements_and_tiny_sets(tmp_path):
    (tmp_path / "labels.csv").write_text("file,statements\na.csv,NOT_A_CODE\n")
    with pytest.raises(ValueError, match="unknown statements"):
        siteconfig.draft(tmp_path, tmp_path / "labels.csv", "s")
    (tmp_path / "labels.csv").write_text("file,statements\na.csv,AFIB\n")
    with pytest.raises(ValueError, match="only 0 usable"):
        siteconfig.draft(tmp_path, tmp_path / "labels.csv", "s")
