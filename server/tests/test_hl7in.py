import socket
import time

import ingest_writers as w
from cardiotic_server import hl7in
from helpers import Client

A04 = "MSH|^~\\&|HIS|HOSP|CARDIOTIC|HOSP|20261031101500||ADT^A04^ADT_A01|MSG001|P|2.5.1\rEVN|A04|20261031101500\rPID|1||UH-20400^^^HOSP^MR~998877^^^NAT^NI||Kulkarni^Ramesh^S||19510203|M\rPV1|1|O|OPD^^^HOSP\r"


def _send(port, text):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(hl7in.START + text.encode() + hl7in.END)
        buf = b""
        while not buf.endswith(hl7in.END):
            buf += s.recv(4096)
    return buf.strip(hl7in.START + hl7in.END).decode()


def _port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def test_adt_register_update_merge_over_mllp(server, ecg):
    port = _port()
    server.hl7in.apply({"enabled": True, "port": port, "host": "127.0.0.1"})
    try:
        ack = _send(port, A04)
        assert "MSA|AA|MSG001" in ack
        c = Client(server.base); c.login("arao")
        p = c.call("GET", "/api/catalog")[1]["patients"]
        assert p[0]["mrn"] == "UH-20400" and p[0]["name"] == "Ramesh Kulkarni" and p[0]["sex"] == "M" and p[0]["birth_date"] == "1951-02-03"
        a08 = A04.replace("ADT^A04", "ADT^A08").replace("MSG001", "MSG002").replace("Kulkarni^Ramesh^S", "Kulkarni\\T\\Rao^Ramesh")
        assert "MSA|AA|MSG002" in _send(port, a08)
        assert c.call("GET", "/api/catalog")[1]["patients"][0]["name"] == "Ramesh Kulkarni&Rao"
        # an ECG filed under a temporary number, then merged into the real record
        t = Client(server.base); t.login("rsawant")
        t.call("POST", "/api/upload", raw=w.csv_file(ecg, 500, comment=False), headers={"X-Fs": "500", "X-Patient-MRN": "TEMP-1"}, expect=201)
        a40 = "MSH|^~\\&|HIS|HOSP|CARDIOTIC|HOSP|20261031||ADT^A40^ADT_A39|MSG003|P|2.5.1\rEVN|A40\rPID|1||UH-20400^^^HOSP^MR\rMRG|TEMP-1^^^HOSP^MR\r"
        assert "MSA|AA|MSG003" in _send(port, a40)
        cat = c.call("GET", "/api/catalog")[1]
        assert [p["mrn"] for p in cat["patients"]] == ["UH-20400"] and cat["ecgs"][0]["patient_id"] == cat["patients"][0]["id"]
        # refusals are acknowledged with the reason
        assert "MSA|AE" in _send(port, A04.replace("UH-20400^^^HOSP^MR~998877^^^NAT^NI", "").replace("MSG001", "MSG004"))
        assert "MSA|AR" in _send(port, A04.replace("ADT^A04", "SIU^S12").replace("MSG001", "MSG005"))
        assert "MSA|AR" in _send(port, "garbage")
        actions = [a["action"] for a in c.call("GET", "/api/audit")[1]]
        assert {"Registered patient from HIS", "Updated patient from HIS", "Merged patients from HIS"} <= set(actions)
        st = server.db.get_setting("feed_status")["HIS (ADT/orders)"]
        assert st["received"] == 3 and st["failed"] == 3
    finally:
        server.hl7in.stop()


def test_ecg_order_fills_doctor_and_location(server, ecg):
    msg, code, _ = hl7in.handle(server, "MSH|^~\\&|HIS|HOSP|CARDIOTIC|HOSP|2026||ORM^O01|M9|P|2.5.1\rPID|1||UH-555^^^HOSP^MR||Iyer^Meera||19600101|F\rPV1|1|E|Emergency^^^HOSP\rORC|NW|ORD-77||||||||||12345^Sharma^Vivek^^^Dr.\rOBR|1|ORD-77||11524-6^EKG study^LN\r")
    assert code == "AA"
    t = Client(server.base); t.login("rsawant")
    rec = t.call("POST", "/api/upload", raw=w.csv_file(ecg, 500, comment=False), headers={"X-Fs": "500", "X-Patient-MRN": "UH-555"}, expect=201)[1]
    assert rec["ordered_by"] == "Dr. Vivek Sharma" and rec["location"] == "Emergency"
    assert hl7in.order_for(server, "UH-555") is None  # used once


def test_inbound_settings(server):
    a = Client(server.base); a.login("kdesai")
    port = _port()
    a.call("PUT", "/api/his", {"enabled": False, "inbound": {"enabled": True, "port": port}}, expect=200)
    try:
        assert "MSA|AA" in _send(port, A04)
    finally:
        a.call("PUT", "/api/his", {"enabled": False, "inbound": {"enabled": False, "port": port}}, expect=200)
    time.sleep(0.2)
    s = socket.socket()
    assert s.connect_ex(("127.0.0.1", port)) != 0
    s.close()
