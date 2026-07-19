"""Investor-readable rendering for universe readiness and integrity."""

from __future__ import annotations

from decimal import Decimal

from alpha.point_in_time_universe.models import UniverseManifest


def render_executive_report(manifest: UniverseManifest) -> str:
    coverage = manifest.coverage
    index_lines = "\n".join(
        f"- {index_name}: {known} of {coverage.sessions} sessions known"
        for index_name, known in coverage.index_known_sessions
    )
    universe_coverage = _percent(coverage.sessions_with_universe, coverage.sessions)
    listing_coverage = _percent(
        coverage.listing_dates_known, coverage.security_master_size
    )
    delisting_coverage = _percent(
        coverage.delisting_dates_known, coverage.security_master_size
    )
    return (
        "# Point-in-Time Historical Universe Foundation v1.0\n\n"
        "## Research Contract\n\n"
        "- Production Influence: false\n"
        f"- Dataset Version: {manifest.dataset_version}\n"
        f"- Build ID: {manifest.build_id}\n"
        f"- Source Fingerprint: {manifest.source_fingerprint}\n\n"
        "## Historical Universe\n\n"
        f"- Security Master Size: {coverage.security_master_size:,}\n"
        f"- Instrument Types Known: {coverage.instrument_types_known:,}\n"
        f"- Sessions: {coverage.sessions:,}\n"
        f"- Date Range: {coverage.first_session} to {coverage.last_session}\n"
        f"- Observed Membership Rows: {coverage.observation_rows:,}\n"
        f"- Sessions With Observed Universe: {universe_coverage}\n"
        f"- Listing-Date Coverage: {listing_coverage}\n"
        f"- Delisting-Date Coverage: {delisting_coverage}\n"
        f"- Sector Intervals Known: {coverage.sector_known_security_intervals:,}\n"
        f"- Corporate Actions Known: {coverage.corporate_actions_known:,}\n"
        f"- Unknown-History Percentage: {coverage.unknown_history_percentage:.2f}%\n"
        f"- Confidence: {coverage.confidence.value}\n\n"
        "## Historical Index Coverage\n\n"
        f"{index_lines}\n\n"
        "## Survivorship Audit\n\n"
        f"- Hard Failures: {coverage.survivorship_failures:,}\n"
        "- Future constituents are never substituted for unknown historical members.\n"
        "- A same-day valid OHLCV observation proves local tradability on that "
        "date only.\n"
        "- First local observation is not represented as an official IPO date.\n"
        "- Last local observation is not represented as an official delisting date.\n"
        "- Equity eligibility is unknown because legacy rows do not retain series or "
        "instrument type.\n\n"
        "## Readiness Conclusion\n\n"
        "The observed-price universe is point-in-time safe against future-constituent "
        "leakage, but institutional replay remains blocked for index-, sector-, "
        "delisting-, and corporate-action-conditioned research until authoritative "
        "histories are ingested.\n\n"
        "`PRODUCTION_INFLUENCE=false`\n"
    )


def _percent(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "unavailable"
    value = Decimal(numerator) / Decimal(denominator) * Decimal("100")
    return f"{value:.2f}%"


__all__ = ["render_executive_report"]
