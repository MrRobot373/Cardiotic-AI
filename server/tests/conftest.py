import sys
import threading
from pathlib import Path

import numpy as np
import pytest

ENGINE_TESTS = Path(__file__).resolve().parents[2] / "engine" / "tests"
sys.path.insert(0, str(ENGINE_TESTS))  # reuse the format writers and the real PTB-XL fixture ECG

import ingest_writers as w  # noqa: E402
from cardiotic_server import auth  # noqa: E402
from cardiotic_server.app import make_app  # noqa: E402

PASSWORD = "correct horse battery"


@pytest.fixture(scope="session")
def ecg():
    return np.load(ENGINE_TESTS / "fixtures" / "fixtures.npz")["ecg12"]


@pytest.fixture(scope="session")
def engine():
    from cardiotic_engine.api import Engine
    return Engine()


@pytest.fixture()
def server(tmp_path, engine):
    httpd, store, worker = make_app(tmp_path / "t.db", None, engine, "127.0.0.1", 0, start_worker=False)
    for u, n, r in (("arao", "Dr. Ananya Rao", "cardiologist"), ("rsawant", "Rohit Sawant", "technician"), ("kdesai", "Kiran Desai", "admin")):
        auth.create_user(store.db, u, n, r, PASSWORD)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    store.base = f"http://127.0.0.1:{httpd.server_address[1]}"
    store.worker = worker
    yield store
    httpd.shutdown()
    httpd.server_close()
