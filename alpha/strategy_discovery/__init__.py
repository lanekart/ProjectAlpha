"""Diagnostic-only walk-forward strategy discovery and generalisation."""

from alpha.strategy_discovery.discovery_service import StrategyDiscoveryService
from alpha.strategy_discovery.models import PRODUCTION_INFLUENCE
from alpha.strategy_discovery.shadow_candidate_publisher import (
    ShadowCandidatePublisher,
)

__all__ = [
    "PRODUCTION_INFLUENCE",
    "ShadowCandidatePublisher",
    "StrategyDiscoveryService",
]
