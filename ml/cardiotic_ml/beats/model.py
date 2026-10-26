"""Beat classifier: 1D-CNN over the beat shape + an MLP over RR-interval timing features.

Shape tells ventricular beats (wide, different morphology) apart; timing (prematurity) is what
separates supraventricular ectopic beats, which often look normal.
"""

import torch
from torch import nn

from cardiotic_ml.beats.dataset import N_RR


def _block(cin: int, cout: int, k: int, stride: int = 1) -> nn.Sequential:
    return nn.Sequential(nn.Conv1d(cin, cout, k, stride=stride, padding=k // 2), nn.BatchNorm1d(cout), nn.ReLU())


class BeatNet(nn.Module):
    def __init__(self, n_classes: int = 4):
        super().__init__()
        self.cnn = nn.Sequential(
            _block(1, 32, 7), _block(32, 32, 7, stride=2),
            _block(32, 64, 5), _block(64, 64, 5, stride=2),
            _block(64, 96, 3), nn.AdaptiveAvgPool1d(8),
        )
        self.rr = nn.Sequential(nn.Linear(N_RR, 32), nn.ReLU(), nn.Linear(32, 32), nn.ReLU())
        self.head = nn.Sequential(nn.Linear(96 * 8 + 32, 128), nn.ReLU(), nn.Dropout(0.3), nn.Linear(128, n_classes))

    def forward(self, x: torch.Tensor, rr: torch.Tensor) -> torch.Tensor:
        h = self.cnn(x.unsqueeze(1)).flatten(1)
        return self.head(torch.cat([h, self.rr(rr)], dim=1))
