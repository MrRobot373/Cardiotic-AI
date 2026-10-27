"""Rhythm model (M3): 1D ResNet over a 30 s, 150 Hz single-lead window + RR-irregularity MLP."""

import torch
from torch import nn

from cardiotic_ml.rhythm.dataset import N_RRF


class ResBlock(nn.Module):
    def __init__(self, cin: int, cout: int, stride: int, k: int = 9):
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv1d(cin, cout, k, stride=stride, padding=k // 2, bias=False), nn.BatchNorm1d(cout), nn.ReLU(),
            nn.Dropout(0.1),
            nn.Conv1d(cout, cout, k, padding=k // 2, bias=False), nn.BatchNorm1d(cout),
        )
        self.skip = nn.Identity() if cin == cout and stride == 1 else nn.Sequential(
            nn.Conv1d(cin, cout, 1, stride=stride, bias=False), nn.BatchNorm1d(cout))
        self.act = nn.ReLU()

    def forward(self, x):
        return self.act(self.body(x) + self.skip(x))


class RhythmNet(nn.Module):
    def __init__(self, n_classes: int = 4, n_rrf: int = N_RRF):
        super().__init__()
        self.stem = nn.Sequential(nn.Conv1d(1, 32, 15, stride=2, padding=7, bias=False), nn.BatchNorm1d(32), nn.ReLU())
        self.res = nn.Sequential(
            ResBlock(32, 32, 2), ResBlock(32, 64, 2), ResBlock(64, 64, 2),
            ResBlock(64, 128, 2), ResBlock(128, 128, 2), ResBlock(128, 128, 1),
        )
        self.rr = nn.Sequential(nn.Linear(n_rrf, 32), nn.ReLU(), nn.Linear(32, 32), nn.ReLU())
        self.head = nn.Sequential(nn.Linear(128 * 2 + 32, 128), nn.ReLU(), nn.Dropout(0.3), nn.Linear(128, n_classes))

    def forward(self, x: torch.Tensor, rr: torch.Tensor) -> torch.Tensor:
        h = self.res(self.stem(x.unsqueeze(1)))
        pooled = torch.cat([h.mean(-1), h.amax(-1)], dim=1)
        return self.head(torch.cat([pooled, self.rr(rr)], dim=1))
