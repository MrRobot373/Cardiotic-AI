"""Shared training loop and metrics (per-class sensitivity / positive predictivity, as in EC57)."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


def set_seed(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)


def class_report(y_true: np.ndarray, y_pred: np.ndarray, labels: list[str]) -> dict:
    k = len(labels)
    cm = np.zeros((k, k), dtype=np.int64)
    for t, p in zip(y_true, y_pred):
        cm[t, p] += 1
    per = {}
    for i, name in enumerate(labels):
        tp = cm[i, i]
        fn = cm[i].sum() - tp
        fp = cm[:, i].sum() - tp
        se = tp / (tp + fn) if tp + fn else float("nan")
        ppv = tp / (tp + fp) if tp + fp else float("nan")
        f1 = 2 * se * ppv / (se + ppv) if se + ppv and not np.isnan(se + ppv) else float("nan")
        per[name] = {"support": int(cm[i].sum()), "sensitivity": se, "ppv": ppv, "f1": f1}
    f1s = [v["f1"] for v in per.values() if not np.isnan(v["f1"])]
    return {
        "accuracy": float(np.trace(cm) / cm.sum()) if cm.sum() else float("nan"),
        "macro_f1": float(np.mean(f1s)) if f1s else float("nan"),
        "per_class": per,
        "confusion": cm.tolist(),
        "labels": labels,
    }


@dataclass
class TrainConfig:
    epochs: int = 12
    batch_size: int = 256
    lr: float = 1e-3
    weight_decay: float = 1e-4
    seed: int = 7
    class_weights: list[float] | None = None
    label_smoothing: float = 0.0
    # Training-only input augmentation: f(*inputs) -> inputs. Never applied to validation/test.
    augment: Callable[..., tuple[torch.Tensor, ...]] | None = None
    log: list[str] = field(default_factory=list)


def _loader(tensors: tuple[torch.Tensor, ...], batch: int, shuffle: bool) -> DataLoader:
    return DataLoader(TensorDataset(*tensors), batch_size=batch, shuffle=shuffle)


@torch.no_grad()
def predict_logits(model: nn.Module, inputs: tuple[torch.Tensor, ...], batch: int = 1024) -> np.ndarray:
    model.eval()
    return torch.cat([model(*chunk) for chunk in _loader(inputs, batch, shuffle=False)]).numpy()


def predict(model: nn.Module, inputs: tuple[torch.Tensor, ...], batch: int = 1024) -> np.ndarray:
    return torch.softmax(torch.from_numpy(predict_logits(model, inputs, batch)), dim=1).numpy()


def train(model: nn.Module, train_inputs: tuple[torch.Tensor, ...], y_train: torch.Tensor,
          val_inputs: tuple[torch.Tensor, ...], y_val: np.ndarray, labels: list[str],
          cfg: TrainConfig) -> tuple[nn.Module, dict]:
    """Train; keep the epoch with the best validation macro-F1 (validation = held-out patients)."""
    set_seed(cfg.seed)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=cfg.epochs)
    w = torch.tensor(cfg.class_weights, dtype=torch.float32) if cfg.class_weights else None
    loss_fn = nn.CrossEntropyLoss(weight=w, label_smoothing=cfg.label_smoothing)
    best, best_f1, history = None, -1.0, []
    for epoch in range(cfg.epochs):
        model.train()
        t0, total, n = time.time(), 0.0, 0
        for *xb, yb in _loader((*train_inputs, y_train), cfg.batch_size, shuffle=True):
            opt.zero_grad()
            if cfg.augment:
                xb = cfg.augment(*xb)
            loss = loss_fn(model(*xb), yb)
            loss.backward()
            opt.step()
            total += loss.item() * len(yb)
            n += len(yb)
        sched.step()
        rep = class_report(y_val, predict(model, val_inputs).argmax(1), labels)
        history.append({"epoch": epoch + 1, "train_loss": total / n, "val_macro_f1": rep["macro_f1"],
                        "val_accuracy": rep["accuracy"], "seconds": round(time.time() - t0, 1)})
        msg = f"epoch {epoch + 1:2d}  loss {total / n:.4f}  val macro-F1 {rep['macro_f1']:.4f}  ({time.time() - t0:.0f}s)"
        print(msg, flush=True)
        cfg.log.append(msg)
        if rep["macro_f1"] > best_f1:
            best_f1, best = rep["macro_f1"], copy.deepcopy(model.state_dict())
    model.load_state_dict(best)
    return model, {"history": history, "best_val_macro_f1": best_f1}
