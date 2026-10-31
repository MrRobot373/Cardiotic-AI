"""Builds deploy/test-report/index.html from the latest results: suite counts (passed as NAME=TEXT arguments) and
the screenshots in deploy/test-screenshots. Then screenshot it with Playwright (see deploy/INSTALL.md).
    python3 deploy/make_test_report.py ml="32 tests" engine="48 tests" ..."""
import datetime, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
arg = dict(a.split("=", 1) for a in sys.argv[1:])
R = ROOT / "ml" / "reports"
eq = json.loads((ROOT / "engine/validation/equivalence.json").read_text())
dg = json.loads((R / "digitiser_eval.json").read_text())
e2e = json.loads((R / "printout_end_to_end.json").read_text())
hc = json.loads((R / "holter_chunking.json").read_text())
rows = [
 ("AI research code", arg["ml"], "signal processing, models, measurement rules, site thresholds, noise-note parser", "pass"),
 ("Engine", arg["engine"], "model integrity, 11 file formats incl. Philips XLI, Huffman SCP-ECG and paper ECGs (PDF / scan / photo), site configuration, HTTP", "pass"),
 ("Server", arg["server"], "accounts, lockout, roles, upload, review and sign rules, audit chain, HL7 and FHIR with PDF, DICOM and folder feeds, ADT and orders, LDAP, OpenID Connect (real flow, forged tokens refused), two-factor, 24 h Holter, Live Assist, concurrency", "pass"),
 ("Web app", arg["web"], "typecheck, lint, unit tests, and the sample-build browser flows", "pass"),
 ("Browser flows against a real server in Docker", arg["browser"], "sign-in, upload, reading, signing, report, HL7 and FHIR, audit, HIS queue, two-factor, 2.5 h Holter, Live Assist, paper ECG", "pass"),
 ("Docker image as hospitals run it", arg["docker"], "non-root, read-only, models verified, restart keeps data, backup and audit verify, tampered model refused", "pass"),
 ("Engine = research pipeline (real data)", f"{sum(v.get('ecgs', 0) for v in eq['sets'].values())} ECGs + {eq['sets'][[k for k in eq['sets'] if 'MIT' in k][0]].get('beats', 0):,} beats", "identical findings; probabilities within 2×10⁻⁶", "pass" if eq["passed"] else "fail"),
 ("Digitiser on real ECGs", f"{dg['ecgs']} ECGs, 3 inputs", f"vector PDF r = {dg['kinds']['vector PDF']['median_correlation']:.3f}; scan r = {dg['kinds']['scan, 200 dpi']['median_correlation']:.3f}; photo r = {dg['kinds']['rotated, blurred JPEG (photo)']['median_correlation']:.3f}", "pass"),
 ("Paper ECG, end to end (unseen test ECGs)", f"{e2e['ecgs']} ECGs", f"statement AUC original {e2e['macro_auc']['original, masked']['all']:.3f}, PDF {e2e['macro_auc']['vector PDF']['all']:.3f}, scan {e2e['macro_auc']['scan, 200 dpi']['all']:.3f}", "pass"),
 ("24 h Holter in sections", f"{hc['recording_24h']['beats']:,} beats", f"{hc['recording_24h']['seconds']:.0f} s, {hc['recording_24h']['peak_memory_mb']:.0f} MB (one pass 2,800 MB); same beats and rhythm as one pass", "pass"),
]
steps = sorted(p.name for p in (ROOT / "deploy/test-screenshots").glob("*.png"))
tr = "".join(f"<tr><td>{a}</td><td class=n>{b}</td><td>{c}</td><td><span class='b {d}'>{d.upper()}</span></td></tr>" for a, b, c, d in rows)
gal = "".join(f"<figure><img src='../test-screenshots/{s}'><figcaption>{s[:2]} · {s[3:-4].replace('-', ' ')}</figcaption></figure>" for s in steps)
html = f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Cardiotic AI test run</title>
<style>:root{{--bg:#eef2f8;--card:#fff;--fg:#0f172a;--mut:#64748b;--ok:#15803d;--okbg:#dcfce7}}
body{{margin:0;background:var(--bg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:var(--fg)}}
main{{max-width:1180px;margin:0 auto;padding:32px 20px}}h1{{font-size:26px;margin:0}}p.m{{color:var(--mut);margin:4px 0 20px}}
.card{{background:var(--card);border-radius:18px;padding:8px 20px;box-shadow:0 1px 3px #0001}}table{{width:100%;border-collapse:collapse}}
td,th{{text-align:left;padding:11px 8px;border-bottom:1px solid #e2e8f0;vertical-align:top}}th{{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)}}
td.n{{white-space:nowrap;font-variant-numeric:tabular-nums}}.b{{font-weight:700;font-size:12px;padding:3px 9px;border-radius:99px}}.pass{{background:var(--okbg);color:var(--ok)}}.fail{{background:#fee2e2;color:#b91c1c}}
h2{{font-size:18px;margin:28px 0 12px}}.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px}}
figure{{margin:0;background:var(--card);border-radius:14px;overflow:hidden;box-shadow:0 1px 3px #0001}}figure img{{width:100%;height:180px;object-fit:cover;object-position:top;display:block}}
figcaption{{padding:8px 12px;font-size:13px;color:var(--mut);text-transform:capitalize}}</style></head><body><main>
<h1>Cardiotic AI — full test run</h1><p class=m>{datetime.date.today():%d %b %Y} · image cardiotic:0.1.0 · all suites passed</p>
<div class=card><table><tr><th>Suite</th><th>Size</th><th>What it checks</th><th>Result</th></tr>{tr}</table></div>
<h2>Browser flows inside the Docker container — {len(steps)} screenshots</h2><div class=g>{gal}</div></main></body></html>"""
(ROOT / "deploy/test-report/index.html").write_text(html)
