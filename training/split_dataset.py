"""Deterministic train/validation split helper."""

from __future__ import annotations

import random
from typing import Any


def split_dataset(
    samples: list[dict[str, Any]],
    validation_ratio: float = 0.15,
    seed: int = 42,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items = list(samples)
    random.Random(seed).shuffle(items)
    size = int(len(items) * validation_ratio)
    return items[size:], items[:size]
