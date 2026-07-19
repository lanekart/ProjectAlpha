from __future__ import annotations

from dataclasses import dataclass

from alpha.market_truth.models import MarketTruthRequest
from alpha.market_truth.provider_registry import (
    MarketTruthProvider,
    MarketTruthProviderRegistry,
)


@dataclass(frozen=True, slots=True)
class ProviderFailoverPlan:
    request_id: str
    providers: tuple[MarketTruthProvider, ...]


class ProviderFailover:
    """Select providers only from registered capability and explicit priority."""

    def plan(
        self,
        registry: MarketTruthProviderRegistry,
        request: MarketTruthRequest,
    ) -> ProviderFailoverPlan:
        providers = registry.providers(request.dataset)
        if request.provider_hint is not None:
            providers = tuple(
                item
                for item in providers
                if item.descriptor.provider_id == request.provider_hint
            )
            if not providers:
                raise KeyError(
                    f"provider {request.provider_hint} does not support "
                    f"{request.dataset.value}"
                )
        return ProviderFailoverPlan(
            request_id=request.request_id,
            providers=providers,
        )


__all__ = ["ProviderFailover", "ProviderFailoverPlan"]
