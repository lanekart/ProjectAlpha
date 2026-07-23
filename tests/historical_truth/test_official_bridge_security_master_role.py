from __future__ import annotations

from alpha.historical_truth.official_bridge_source_role_validation import (
    validate_source_role_url,
)

_SECURITY_MASTER = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"


def test_security_master_is_allowed_only_for_post_identity() -> None:
    post_valid, post_reason = validate_source_role_url(
        "POST_IDENTITY", _SECURITY_MASTER
    )
    pre_valid, pre_reason = validate_source_role_url("PRE_IDENTITY", _SECURITY_MASTER)

    assert post_valid is True
    assert post_reason == "ROLE_SOURCE_STRUCTURALLY_VALID"
    assert pre_valid is False
    assert pre_reason == "PRE_IDENTITY_SOURCE_PATTERN_NOT_APPROVED"


def test_server_rendered_quotes_page_requires_action_api_resolution() -> None:
    valid, reason = validate_source_role_url(
        "CORPORATE_ACTION",
        "https://www.nseindia.com/get-quotes/equity?symbol=AJMERA",
    )

    assert valid is True
    assert reason == "ROLE_SOURCE_REQUIRES_API_RESOLUTION"
