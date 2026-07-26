"""Deterministic statistical helpers for DSI-002I."""

from __future__ import annotations

import hashlib
import random
from decimal import ROUND_HALF_UP, Decimal

_Q6 = Decimal("0.000001")
_Z_95 = Decimal("1.959964")


def wilson_interval(successes: int, total: int) -> tuple[Decimal, Decimal] | None:
    """Return a deterministic 95% Wilson interval for a binomial proportion."""

    if total <= 0 or successes < 0 or successes > total:
        return None
    n = Decimal(total)
    proportion = Decimal(successes) / n
    z2 = _Z_95 * _Z_95
    denominator = Decimal("1") + z2 / n
    centre = (proportion + z2 / (Decimal("2") * n)) / denominator
    spread = (
        _Z_95
        * (
            (
                proportion * (Decimal("1") - proportion) / n
                + z2 / (Decimal("4") * n * n)
            ).sqrt()
        )
        / denominator
    )
    return (
        max(Decimal("0"), centre - spread).quantize(_Q6, rounding=ROUND_HALF_UP),
        min(Decimal("1"), centre + spread).quantize(_Q6, rounding=ROUND_HALF_UP),
    )


def deterministic_bootstrap_interval(
    values: tuple[Decimal, ...],
    *,
    package_identity: str,
    statistic: str,
    samples: int = 2000,
) -> tuple[Decimal, Decimal] | None:
    """Return a deterministic percentile interval for mean, median, or expectancy."""

    if not values or samples < 2:
        return None
    seed_material = f"{package_identity}|{statistic}|{samples}".encode()
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    generator = random.Random(seed)
    estimates: list[Decimal] = []
    for _ in range(samples):
        sample = tuple(values[generator.randrange(len(values))] for _ in values)
        estimates.append(_statistic(sample, statistic))
    estimates.sort()
    low_index = int(Decimal(samples - 1) * Decimal("0.025"))
    high_index = int(Decimal(samples - 1) * Decimal("0.975"))
    return (
        estimates[low_index].quantize(_Q6, rounding=ROUND_HALF_UP),
        estimates[high_index].quantize(_Q6, rounding=ROUND_HALF_UP),
    )


def jaccard(left: frozenset[str], right: frozenset[str]) -> Decimal | None:
    """Return set overlap without treating empty populations as zero overlap."""

    union = left | right
    if not union:
        return None
    return (Decimal(len(left & right)) / Decimal(len(union))).quantize(
        _Q6,
        rounding=ROUND_HALF_UP,
    )


def benjamini_hochberg(
    p_values: tuple[Decimal, ...],
) -> tuple[Decimal, ...]:
    """Return monotone Benjamini-Hochberg adjusted p-values."""

    _validate_p_values(p_values)
    count = len(p_values)
    if count == 0:
        return ()
    ordered = sorted(enumerate(p_values), key=lambda item: (item[1], item[0]))
    adjusted = [Decimal("0")] * count
    running = Decimal("1")
    for reverse_rank, (original, value) in enumerate(reversed(ordered), start=1):
        rank = count - reverse_rank + 1
        candidate = value * Decimal(count) / Decimal(rank)
        running = min(running, candidate, Decimal("1"))
        adjusted[original] = running.quantize(_Q6, rounding=ROUND_HALF_UP)
    return tuple(adjusted)


def holm_adjustment(p_values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    """Return step-down Holm adjusted p-values."""

    _validate_p_values(p_values)
    count = len(p_values)
    ordered = sorted(enumerate(p_values), key=lambda item: (item[1], item[0]))
    adjusted = [Decimal("0")] * count
    running = Decimal("0")
    for rank, (original, value) in enumerate(ordered):
        candidate = value * Decimal(count - rank)
        running = max(running, min(candidate, Decimal("1")))
        adjusted[original] = running.quantize(_Q6, rounding=ROUND_HALF_UP)
    return tuple(adjusted)


def _statistic(values: tuple[Decimal, ...], statistic: str) -> Decimal:
    ordered = tuple(sorted(values))
    if statistic in {"mean", "expectancy"}:
        return sum(ordered, Decimal("0")) / Decimal(len(ordered))
    if statistic == "median":
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / Decimal("2")
    raise ValueError(f"unsupported bootstrap statistic: {statistic}")


def _validate_p_values(values: tuple[Decimal, ...]) -> None:
    if any(value < 0 or value > 1 for value in values):
        raise ValueError("p-values must be between zero and one")


__all__ = [
    "benjamini_hochberg",
    "deterministic_bootstrap_interval",
    "holm_adjustment",
    "jaccard",
    "wilson_interval",
]
