"""Signal-quality model: a small 1D-CNN over a 2.5 s single-lead window (900 samples @ 360 Hz).

Input is in millivolts and not amplitude-normalised on purpose: flat lines, saturation and
lead-off are amplitude phenomena that normalisation would hide.
"""

import torch
from torch import nn


def _block(cin: int, cout: int, k: int) -> nn.Sequential:
    return nn.Sequential(nn.Conv1d(cin, cout, k, stride=2, padding=k // 2), nn.BatchNorm1d(cout), nn.ReLU())


class QualityNet(nn.Module):
    def __init__(self, n_classes: int = 3):
        super().__init__()
        self.features = nn.Sequential(_block(1, 16, 9), _block(16, 32, 7), _block(32, 64, 5), _block(64, 64, 5), _block(64, 96, 3))
        self.head = nn.Sequential(nn.Linear(96 * 2 + 3, 64), nn.ReLU(), nn.Dropout(0.2), nn.Linear(64, n_classes))

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # x: (batch, 900)
        h = self.features(x.unsqueeze(1))
        pooled = torch.cat([h.mean(-1), h.amax(-1)], dim=1)
        # three simple amplitude statistics help with flat-line / saturation detection
        stats = torch.stack([x.std(1), x.abs().amax(1), (x[:, 1:] - x[:, :-1]).abs().mean(1)], dim=1)
        return self.head(torch.cat([pooled, torch.log1p(stats * 10)], dim=1))
