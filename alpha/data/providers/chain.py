from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from alpha.data.models import DownloadResult
from alpha.data.providers.base import MarketDataProvider
from alpha.exceptions import DownloadError


@dataclass(frozen=True, slots=True)
class MarketDataProviderChain(MarketDataProvider):
    """
    Deterministic provider chain for market data fallback.

    The chain tries providers in configured order and returns the first
    successful result. It is the foundation for future live/archive/vendor
    routing without forcing application services to know provider details.
    """

    providers: tuple[MarketDataProvider, ...]

    def __post_init__(self) -> None:
        if len(self.providers) == 0:
            raise ValueError(
                "market data provider chain requires at least one provider"
            )

    @property
    def provider_count(self) -> int:
        """Return number of configured providers."""

        return len(self.providers)

    @property
    def provider_names(self) -> tuple[str, ...]:
        """Return provider names in deterministic execution order."""

        return tuple(_provider_name(provider) for provider in self.providers)

    def download_bhavcopy(self, target_date: date) -> DownloadResult:
        """Download bhavcopy data using the first provider that succeeds."""

        failures: list[str] = []

        for provider in self.providers:
            name = _provider_name(provider)
            try:
                return provider.download_bhavcopy(target_date)
            except DownloadError as exc:
                failures.append(f"{name}: {exc}")

        failure_message = "; ".join(failures) if failures else "no providers attempted"
        raise DownloadError(
            "No market data provider could download bhavcopy for "
            f"{target_date.isoformat()}. Attempts: {failure_message}"
        )


def _provider_name(provider: MarketDataProvider) -> str:
    configured_name = getattr(provider, "provider_name", None)
    if isinstance(configured_name, str) and configured_name.strip():
        return configured_name.strip()
    return provider.__class__.__name__
