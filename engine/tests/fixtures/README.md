# Test fixtures

- `fixtures.npz/ecg12`: PTB-XL 1.0.3 ECG 3009 (500 Hz, 12 leads, mV), test fold. PTB-XL: Wagner P et al.,
  Scientific Data 7:154 (2020), PhysioNet, CC BY 4.0.
- `fixtures.npz/strip`: MIT-BIH Arrhythmia record 233, MLII, 600–660 s (360 Hz, mV). Moody GB, Mark RG,
  IEEE Eng Med Biol 20(3):45-50 (2001), PhysioNet, ODC-By 1.0.
- `golden.json`: engine output for both, produced by `cardiotic-engine` 0.1.0 with models 2026.10.1 and
  checked equal to the research pipeline (validation/equivalence.json). Regenerate only with a new model release.
