from pathlib import Path
import os

# Repo layout: <repo>/ml/cardiotic_ml/paths.py -> <repo>
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("CARDIOTIC_DATA", REPO_ROOT / "data" / "raw"))
MITDB_DIR = DATA_ROOT / "mitdb"
NSTDB_DIR = DATA_ROOT / "nstdb"
ARTIFACTS_DIR = Path(os.environ.get("CARDIOTIC_ARTIFACTS", REPO_ROOT / "ml" / "artifacts"))
REPORTS_DIR = REPO_ROOT / "ml" / "reports"
