"""Compatibility exports for HTR-010B1B continuity and weight closure."""

from alpha.historical_truth.adjustment_replay_admission_continuity_validation import (
    AMBIGUOUS_FACTOR_STATES,
    CERTIFIED_FACTOR_STATES,
    HTR010B1B_CONTRACT_VERSION,
    NON_MULTIPLICATIVE_STATES,
    UNKNOWN_FACTOR_STATES,
    recompute_factor_validation,
)
from alpha.historical_truth.adjustment_replay_admission_quarantine_weight import (
    tier_a_quarantine_economic_weight,
)

__all__ = [
    "AMBIGUOUS_FACTOR_STATES",
    "CERTIFIED_FACTOR_STATES",
    "HTR010B1B_CONTRACT_VERSION",
    "NON_MULTIPLICATIVE_STATES",
    "UNKNOWN_FACTOR_STATES",
    "recompute_factor_validation",
    "tier_a_quarantine_economic_weight",
]
