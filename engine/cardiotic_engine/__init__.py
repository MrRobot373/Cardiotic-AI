"""Cardiotic AI engine: the deployable ECG analysis component (on-premise service or embedded library).

It runs only exported, registered ONNX models listed in `models/manifest.json`, after checking each
file's SHA-256. Analysis logic is shared with the research code (`cardiotic_ml`), so the engine and
the research pipeline give the same results; tests check this.

Research use only. Not a medical device.
"""

__version__ = "0.1.0"
