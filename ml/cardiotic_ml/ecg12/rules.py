"""Measurement-based statements: rate and interval findings decided from our own measurements.

Some statements are definitions on a number, not patterns to learn. Learned thresholds for them
depend on how strictly the training cardiologists wrote them (PTB-XL rarely writes sinus bradycardia
for 55–59 bpm; Chapman always does), so they do not transfer between hospitals. These rules use
published clinical cut-offs, fixed in advance (no tuning):

  SBRAD  sinus rhythm and heart rate < 60 bpm             (AHA/ACCF/HRS 2009 standardisation)
  STACH  sinus rhythm and heart rate > 100 bpm
  1AVB   PR interval > 200 ms
  LNGQT  QTc (Bazett) >= 460 ms                           (AHA/ACCF/HRS 2009: >=450 men, >=460 women)

"Sinus" here means: the statement model does not call atrial fibrillation or flutter, the rhythm
is regular and a P wave was found before every QRS (a PR interval was measured).
"""

from __future__ import annotations

RULES = {
    "SBRAD": "sinus rhythm and heart rate < 60 bpm",
    "STACH": "sinus rhythm and heart rate > 100 bpm",
    "1AVB": "PR interval > 200 ms",
    "LNGQT": "QTc (Bazett) >= 460 ms",
}


def sinus(meas: dict, p_af: float, p_flutter: float, th_af: float, th_flutter: float) -> bool:
    return bool(meas.get("ok")) and meas.get("pr_ms") is not None and p_af < th_af and p_flutter < th_flutter


def rule_statements(meas: dict, is_sinus: bool) -> dict[str, bool]:
    if not meas.get("ok"):
        return {k: False for k in RULES}
    hr, pr, qtc = meas.get("heart_rate_bpm"), meas.get("pr_ms"), meas.get("qtc_bazett_ms")
    return {"SBRAD": is_sinus and hr is not None and hr < 60,
            "STACH": is_sinus and hr is not None and hr > 100,
            "1AVB": pr is not None and pr > 200,
            "LNGQT": qtc is not None and qtc >= 460}
