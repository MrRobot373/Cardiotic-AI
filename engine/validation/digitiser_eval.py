"""How well does the digitiser read printouts back? Real PTB-XL test-fold ECGs are rendered as the product's PDF
report (and, independently, by matplotlib), digitised as vector PDF, 200 dpi scan and a rotated, blurred JPEG
'photo', and compared with the original samples. Writes ml/reports/digitiser_eval.json.
Needs the research data and poppler (pdftoppm). Run: python3 engine/validation/digitiser_eval.py [N]"""

import base64, io, json, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from cardiotic_engine.ingest import LEADS, parse
from cardiotic_ml import dsp
from cardiotic_ml.data import ptbxl
from cardiotic_server import pdf

N = int(sys.argv[1]) if len(sys.argv) > 1 else 40


def score(e, view):
    out = []
    for i, lead in enumerate(LEADS):
        a, b = e.windows[lead]
        ref = np.clip(view[i] - np.median(view[i]), -1.2, 1.2)[a:b]
        got = e.leads[lead][a:b]
        ref, got = ref - np.median(ref), got - np.median(got)
        out.append((float(np.corrcoef(ref, got)[0, 1]), float(np.sqrt(np.mean((ref - got) ** 2)) * 1000)))
    return out


def main():
    res, fails = {"vector PDF": [], "scan, 200 dpi": [], "rotated, blurred JPEG (photo)": []}, {}
    for r in ptbxl.split(ptbxl.TEST_FOLDS)[:N]:
        x = ptbxl.load_signal(r, hr=True)
        view = dsp.bandpass(x, 500, "diagnostic")
        b64 = {l: base64.b64encode(np.clip(np.round(view[i] * 1000), -32767, 32767).astype("<i2").tobytes()).decode() for i, l in enumerate(LEADS)}
        rep = {"id": "E1", "site": "S", "patient": {"name": "T", "mrn": "1", "sex": "", "birth_date": None}, "recorded_at": "2026-01-01T00:00", "location": "", "device": "",
               "ordered_by": "", "measurements": {}, "edited": [], "statements": [], "note": "", "signed_by": "D", "signed_at": "x", "software": "x"}
        data = pdf.ecg_report(rep, b64, 500, draft=False)
        with tempfile.TemporaryDirectory() as d:
            Path(d, "r.pdf").write_bytes(data)
            subprocess.run(["pdftoppm", "-r", "200", "-png", f"{d}/r.pdf", f"{d}/p"], check=True)
            png = Path(d, "p-1.png").read_bytes()
        im = Image.open(io.BytesIO(png)).convert("RGB").rotate(2.0, resample=Image.BICUBIC, fillcolor=(235, 235, 230))
        im = ImageEnhance.Brightness(im.filter(ImageFilter.GaussianBlur(0.8))).enhance(0.85)
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=70)
        for kind, blob in zip(res, (data, png, buf.getvalue())):
            try:
                res[kind] += score(parse(blob), view)
            except Exception as ex:
                fails[kind] = fails.get(kind, 0) + 1
    out = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ecgs": N, "failed_files": fails,
           "kinds": {k: {"leads": len(v), "median_correlation": float(np.median([a for a, _ in v])), "p10_correlation": float(np.percentile([a for a, _ in v], 10)),
                         "median_rmse_uV": float(np.median([b for _, b in v]))} for k, v in res.items() if v}}
    Path(__file__).resolve().parents[2].joinpath("ml/reports/digitiser_eval.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


main()
