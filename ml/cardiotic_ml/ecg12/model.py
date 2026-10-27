"""M4 statement model: 1D ResNet over a 10 s, 100 Hz, 12-lead ECG -> one logit per SCP statement."""

import torch
from torch import nn

from cardiotic_ml.rhythm.model import ResBlock


class ECG12Net(nn.Module):
    def __init__(self, n_out: int, n_leads: int = 12, width: int = 64):
        super().__init__()
        w = width
        self.stem = nn.Sequential(nn.Conv1d(n_leads, w, 15, stride=2, padding=7, bias=False), nn.BatchNorm1d(w), nn.ReLU())
        self.res = nn.Sequential(
            ResBlock(w, w, 1, k=7), ResBlock(w, 2 * w, 2, k=7), ResBlock(2 * w, 2 * w, 1, k=7),
            ResBlock(2 * w, 4 * w, 2, k=7), ResBlock(4 * w, 4 * w, 1, k=7), ResBlock(4 * w, 4 * w, 2, k=5),
        )
        self.head = nn.Sequential(nn.Dropout(0.3), nn.Linear(8 * w, n_out))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.res(self.stem(x))
        return self.head(torch.cat([h.mean(-1), h.amax(-1)], dim=1))
