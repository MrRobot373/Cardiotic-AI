"""Model runners: the analysis pipelines call models as plain functions, arrays in, logits out.

The same pipeline code runs on PyTorch here (research) and on ONNX Runtime in the engine, so there is
one implementation of the analysis and the two back-ends can be compared output for output.
A runner is any callable `runner(*arrays) -> logits` with an `n_out` attribute.
"""

from __future__ import annotations

import numpy as np

BATCH = 256  # bounded memory on long (e.g. 24 h Holter) recordings


def run_batched(runner, *arrays: np.ndarray) -> np.ndarray:
    n = len(arrays[0])
    if n == 0:
        return np.zeros((0, runner.n_out), dtype=np.float32)
    return np.concatenate([runner(*(np.ascontiguousarray(a[i:i + BATCH], dtype=np.float32) for a in arrays))
                           for i in range(0, n, BATCH)])


class TorchRunner:
    def __init__(self, model):
        self.model = model.eval()
        self.n_out = model.head[-1].out_features

    def __call__(self, *arrays: np.ndarray) -> np.ndarray:
        import torch

        with torch.no_grad():
            return self.model(*(torch.from_numpy(a) for a in arrays)).numpy()
