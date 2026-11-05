"""Worklist triage, server side: the same rules as the web app (frontend/src/data/clinical.ts `triage`),
so the server can raise a critical-result notification the moment an ECG arrives. A reading-order aid,
never a diagnosis. tests/test_triage.py checks both implementations agree on shared cases."""

from __future__ import annotations

import re

URGENT = ("AFIB", "AFLT", "2AVB", "LNGQT", "SVTAC", "PSVT", "WPW", "CLBBB")
_MI = re.compile(r"MI$")


def triage(statements: list[dict], m: dict, names: dict[str, str] | None = None) -> dict:
    names = names or {}
    codes = [s["statement"] for s in statements]
    have = set(codes)
    hr = float(m.get("heart_rate_bpm") or 0)
    qtc = float(m.get("qtc_bazett_ms") or 0)
    name = lambda c: names.get(c, c)  # noqa: E731
    if "3AVB" in have:
        return {"priority": "critical", "reason": "Complete heart block suggested"}
    if ("AFIB" in have or "AFLT" in have) and hr >= 120:
        return {"priority": "critical", "reason": f"AF/flutter with rate {_r(hr)} bpm"}
    wide = float(m.get("qrs_ms") or 0) >= 120 or "PACE" in have  # QTc is not interpretable with a wide QRS
    if qtc >= 500 and not wide:
        return {"priority": "critical", "reason": f"QTc {_r(qtc)} ms"}
    if hr >= 150 or 0 < hr < 40:
        return {"priority": "critical", "reason": f"Rate {_r(hr)} bpm"}
    mi = next((c for c in codes if _MI.search(c) and not c.startswith("SUPER_")), None)
    if mi:
        return {"priority": "urgent", "reason": name(mi)}
    u = next((c for c in codes if c in URGENT), None)
    if u:
        return {"priority": "urgent", "reason": name(u)}
    abnormal = [c for c in codes if not c.startswith("SUPER_") and c not in ("NORM", "SR")]
    if abnormal or "NORM" not in have:
        return {"priority": "routine", "reason": name(abnormal[0]) if abnormal else "Not classified normal"}
    return {"priority": "normal", "reason": "Normal ECG"}


def _r(x: float) -> int:
    """Math.round in JavaScript (halves go up), so both sides print the same number."""
    import math
    return int(math.floor(x + 0.5))
