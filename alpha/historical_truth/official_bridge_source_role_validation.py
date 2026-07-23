"""Source-role validation for HTR-010B1F official evidence URLs."""

from __future__ import annotations

from urllib.parse import urlparse

HTR010B1F_SOURCE_ROLE_CONTRACT_VERSION = "HTR-010B1F-SOURCE-ROLE-v1.0.0"

_ALLOWED_HOST_SUFFIXES = (
    "nseindia.com",
    "nsearchives.nseindia.com",
    "archives.nseindia.com",
    "bseindia.com",
    "sebi.gov.in",
    "nsdl.co.in",
    "cdslindia.com",
)


def validate_source_role_url(role: str, source_url: str) -> tuple[bool, str]:
    """Validate whether an official URL is structurally suitable for its role."""

    if not source_url:
        return False, "MISSING_SOURCE_URL"

    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    official = parsed.scheme == "https" and any(
        host == suffix or host.endswith("." + suffix)
        for suffix in _ALLOWED_HOST_SUFFIXES
    )
    if not official:
        return False, "SOURCE_URL_NOT_OFFICIAL_HTTPS"

    normalized_role = role.upper()
    is_quote_page = path.startswith("/get-quote/equity/") or path.startswith(
        "/get-quotes/equity"
    )
    is_xbrl = host == "nsearchives.nseindia.com" and "/corporate/ixbrl/" in path
    is_security_master = (
        host == "nsearchives.nseindia.com"
        and path.endswith("/content/equities/equity_l.csv")
    )
    is_generic_actions = path.startswith(
        "/companies-listing/corporate-filings-actions"
    )

    if normalized_role == "CORPORATE_ACTION":
        if is_generic_actions:
            return False, "GENERIC_DYNAMIC_ACTION_TABLE_NOT_ROLE_EVIDENCE"
        if is_quote_page or is_xbrl:
            return True, "ROLE_SOURCE_STRUCTURALLY_VALID"
        return False, "ACTION_SOURCE_PATTERN_NOT_APPROVED"

    if normalized_role == "PRE_IDENTITY":
        if is_xbrl:
            return True, "ROLE_SOURCE_STRUCTURALLY_VALID"
        return False, "PRE_IDENTITY_SOURCE_PATTERN_NOT_APPROVED"

    if normalized_role == "POST_IDENTITY":
        if is_xbrl or is_quote_page or is_security_master:
            return True, "ROLE_SOURCE_STRUCTURALLY_VALID"
        return False, "POST_IDENTITY_SOURCE_PATTERN_NOT_APPROVED"

    return False, "UNKNOWN_EVIDENCE_ROLE"


__all__ = [
    "HTR010B1F_SOURCE_ROLE_CONTRACT_VERSION",
    "validate_source_role_url",
]
