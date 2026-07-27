# ruff: noqa: E501
from __future__ import annotations

import json
from pathlib import Path


MODULE = Path("alpha/decision_superiority/pre2016_calendar_recovery.py")
EARLY_REGISTRY = Path("config/dsi010_pre2011_official_calendar_candidates.json")
TESTS = Path("tests/decision_superiority/test_pre2016_calendar_recovery_later_years.py")
DOCS = Path("docs/DSI-010_PRE2011_OFFICIAL_CALENDAR_RECOVERY.md")

HTML_TEXT_HASHES = {
    "NSE_CMTR_5633_2005_ANNUAL_CALENDAR": "86a82651f898770979ec9eed3ed94dad367780824b8c933275912ae64860df5c",
    "NSE_CMTR_6787_2005_HOLIDAY_AMENDMENT": "761465abc1eb66e01ba2df6b4dce2a9e580d48a9af102e633f398a54d558e829",
    "NSE_CMTR_6793_2005_SPECIAL_SESSION": "429203fc74a7b6998afa3aa5f3d4f74396aad577b09b0694a40960d4a41df7a6",
    "NSE_CMTR_6946_2006_ANNUAL_CALENDAR": "615b9923f59e2db29cb5c3243f3b5b23400258ed3c53017e790233a19504bf92",
    "NSE_CMTR_7977_2006_SPECIAL_SESSION": "282232b802bc8ddd9599d008e8be62a7bfecf0a82cb282c86376ffbfba1214a4",
    "NSE_CMTR_8182_2007_ANNUAL_CALENDAR": "fd36d031b11ebeeb9118c5e1ac858f3f617398853d57d72144068bdf30054923",
    "NSE_CMTR_9666_2007_SPECIAL_SESSION": "b33c9afc89f0bc722a9c638cd84c7e6c8028eac718bece0364df2ebf1ae460e9",
    "NSE_CMTR_9908_2008_ANNUAL_CALENDAR": "b08b1b2579234bd4569b67880f87dd7835f984505e8ba22d5f2d2b4999214ae8",
    "NSE_CMTR_11371_2008_SPECIAL_SESSION": "6a08e714315d7d54a89a5c14d34463368cec50b776ba6162d8fb60e97748f06c",
    "NSE_CMTR_11733_2009_ANNUAL_CALENDAR": "4f115ab5af910c83bd6b3a236beef0ec2a6b428d3477d05d6eb9144c1830d085",
    "NSE_CMTR_12236_2009_HOLIDAY_AMENDMENT": "c559da80162d0d54bb0f66f819ae0a205f960b34afaea8a4e838d9235c9d8821",
    "NSE_CMTR_13174_2009_SPECIAL_SESSION": "6e0867f86fe3daa731111739d276d1336c17e7b397c51c126840e02494e79e4c",
    "NSE_CMTR_13194_2009_HOLIDAY_AMENDMENT": "8eadcc58fd2ceffcd6ea83bfee1c1a25df8d6c70b7969131838c783b7b315569",
}


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"PATCH_TARGET_MISSING:{label}")
    return text.replace(old, new, 1)


def patch_module() -> None:
    text = MODULE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    expected_sha256: str | None\n"
        "    expected_download_number: str | None\n",
        "    expected_sha256: str | None\n"
        "    expected_extracted_text_sha256: str | None\n"
        "    expected_download_number: str | None\n",
        "candidate canonical hash field",
    )
    text = replace_once(
        text,
        "    response_sha256: str | None = None\n"
        "    pdf_signature_valid: bool = False\n",
        "    response_sha256: str | None = None\n"
        "    raw_sha256_match: bool = False\n"
        "    pdf_signature_valid: bool = False\n",
        "attempt raw hash field",
    )
    text = replace_once(
        text,
        "    extracted_text_sha256: str | None = None\n"
        "    exchange_match: bool = False\n",
        "    extracted_text_sha256: str | None = None\n"
        "    extracted_text_sha256_match: bool = False\n"
        "    html_transport_drift_accepted: bool = False\n"
        "    exchange_match: bool = False\n",
        "attempt canonical hash fields",
    )
    text = replace_once(
        text,
        '        "cross_segment_only_sources": partial,\n'
        '        "calendar_certification_permitted": False,\n',
        '        "cross_segment_only_sources": partial,\n'
        '        "html_transport_drift_accepted": sum(\n'
        '            attempt.html_transport_drift_accepted for attempt in result.attempts\n'
        '        ),\n'
        '        "calendar_certification_permitted": False,\n',
        "summary drift count",
    )
    text = replace_once(
        text,
        "        response_sha256=digest,\n"
        "        pdf_signature_valid=pdf_signature,\n",
        "        response_sha256=digest,\n"
        "        raw_sha256_match=(\n"
        "            candidate.expected_sha256 is None\n"
        "            or digest == candidate.expected_sha256\n"
        "        ),\n"
        "        pdf_signature_valid=pdf_signature,\n",
        "base raw hash match",
    )
    text = replace_once(
        text,
        "    if candidate.expected_sha256 and digest != candidate.expected_sha256:\n"
        "        return replace(\n"
        "            base,\n"
        '            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",\n'
        '            error="SOURCE_DOCUMENT_HASH_MISMATCH",\n'
        "        )\n"
        "    if digest is None:\n",
        "    if digest is None:\n",
        "defer raw hash mismatch",
    )
    text = replace_once(
        text,
        "    text_path, text_digest = _persist_text(candidate, extracted, digest, text)\n"
        "    checks = _validate_content(candidate, text)\n",
        "    text_path, text_digest = _persist_text(candidate, extracted, digest, text)\n"
        "    raw_hash_match = (\n"
        "        candidate.expected_sha256 is None or digest == candidate.expected_sha256\n"
        "    )\n"
        "    text_hash_match = (\n"
        "        candidate.expected_extracted_text_sha256 is None\n"
        "        or text_digest == candidate.expected_extracted_text_sha256\n"
        "    )\n"
        "    html_transport_drift_accepted = (\n"
        '        document_format == "HTML"\n'
        "        and not raw_hash_match\n"
        "        and candidate.expected_extracted_text_sha256 is not None\n"
        "        and text_hash_match\n"
        "    )\n"
        "    hash_boundary_passed = raw_hash_match or html_transport_drift_accepted\n"
        "    if not hash_boundary_passed:\n"
        "        return replace(\n"
        "            base,\n"
        '            text_extraction_status="EXTRACTED",\n'
        "            extracted_text_sha256=text_digest,\n"
        "            extracted_text_sha256_match=text_hash_match,\n"
        '            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",\n'
        '            extracted_text_path=str(text_path),\n'
        '            error="SOURCE_DOCUMENT_HASH_MISMATCH",\n'
        "        )\n"
        "    if not text_hash_match:\n"
        "        return replace(\n"
        "            base,\n"
        '            text_extraction_status="EXTRACTED",\n'
        "            extracted_text_sha256=text_digest,\n"
        "            extracted_text_sha256_match=False,\n"
        '            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",\n'
        '            extracted_text_path=str(text_path),\n'
        '            error="EXTRACTED_TEXT_HASH_MISMATCH",\n'
        "        )\n"
        "    checks = _validate_content(candidate, text)\n",
        "canonical hash boundary",
    )
    text = replace_once(
        text,
        "        extracted_text_sha256=text_digest,\n"
        "        exchange_match=checks[\"exchange_match\"],\n",
        "        extracted_text_sha256=text_digest,\n"
        "        extracted_text_sha256_match=text_hash_match,\n"
        "        html_transport_drift_accepted=html_transport_drift_accepted,\n"
        "        exchange_match=checks[\"exchange_match\"],\n",
        "attempt canonical result",
    )
    text = replace_once(
        text,
        "    expected_sha256 = _optional_string(payload.get(\"expected_sha256\"))\n"
        "    if expected_sha256 is not None and not re.fullmatch(\n"
        "        r\"[0-9a-f]{64}\", expected_sha256\n"
        "    ):\n"
        "        raise Pre2016ExternalValidationError(\"PRE2011_CALENDAR_EXPECTED_SHA256_INVALID\")\n",
        "    expected_sha256 = _optional_string(payload.get(\"expected_sha256\"))\n"
        "    if expected_sha256 is not None and not re.fullmatch(\n"
        "        r\"[0-9a-f]{64}\", expected_sha256\n"
        "    ):\n"
        "        raise Pre2016ExternalValidationError(\"PRE2011_CALENDAR_EXPECTED_SHA256_INVALID\")\n"
        "    expected_extracted_text_sha256 = _optional_string(\n"
        "        payload.get(\"expected_extracted_text_sha256\")\n"
        "    )\n"
        "    if expected_extracted_text_sha256 is not None and not re.fullmatch(\n"
        "        r\"[0-9a-f]{64}\", expected_extracted_text_sha256\n"
        "    ):\n"
        "        raise Pre2016ExternalValidationError(\n"
        '            "PRE2011_CALENDAR_EXPECTED_TEXT_SHA256_INVALID"\n'
        "        )\n",
        "candidate canonical hash parser",
    )
    text = replace_once(
        text,
        "        expected_sha256=expected_sha256,\n"
        "        expected_download_number=_optional_string(\n",
        "        expected_sha256=expected_sha256,\n"
        "        expected_extracted_text_sha256=expected_extracted_text_sha256,\n"
        "        expected_download_number=_optional_string(\n",
        "candidate canonical hash constructor",
    )
    MODULE.write_text(text, encoding="utf-8")


def patch_registry() -> None:
    payload = json.loads(EARLY_REGISTRY.read_text(encoding="utf-8"))
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise RuntimeError("EARLY_REGISTRY_INVALID")
    observed: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise RuntimeError("EARLY_REGISTRY_ROW_INVALID")
        source_id = str(candidate.get("source_id") or "")
        expected = HTML_TEXT_HASHES.get(source_id)
        if expected is None:
            continue
        candidate["expected_extracted_text_sha256"] = expected
        observed.add(source_id)
    if observed != set(HTML_TEXT_HASHES):
        raise RuntimeError(
            f"EARLY_REGISTRY_SOURCE_MISMATCH:{sorted(set(HTML_TEXT_HASHES) - observed)}"
        )
    EARLY_REGISTRY.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def patch_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")
    marker = "\n\ndef test_2015_capital_market_calendar_is_accepted(\n"
    addition = '''

def _html_registry(
    root: Path,
    *,
    url: str,
    expected_raw: bytes,
    expected_text: str,
) -> Path:
    path = root / "html_candidate_registry.json"
    text_digest = hashlib.sha256(
        (expected_text.rstrip() + "\n").encode("utf-8")
    ).hexdigest()
    path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "year": 2009,
                        "source_id": "NSE_CMTR_HTML_DRIFT",
                        "source_url": url,
                        "segment_scope": "CAPITAL_MARKET",
                        "expected_sha256": hashlib.sha256(expected_raw).hexdigest(),
                        "expected_extracted_text_sha256": text_digest,
                        "expected_download_number": None,
                        "expected_circular_date": None,
                        "expected_subject": "trading holiday on april 30, 2009",
                        "requires_muhurat_statement": False,
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_official_html_transport_drift_accepts_identical_visible_text(
    tmp_path: Path,
) -> None:
    url = "https://nsearchives.nseindia.com/content/circulars/cmtr12236.htm"
    visible = (
        "National Stock Exchange of India Limited\n"
        "Capital Market Segment\n"
        "Trading holiday on April 30, 2009\n"
        "April 30, 2009 Parliamentary Elections"
    )
    expected_raw = (
        "<html><body>" + visible.replace("\n", "<br>") + "</body></html>"
    ).encode()
    drifted_raw = (
        "<html><head><script>request specific telemetry</script></head><body>"
        + visible.replace("\n", "<br>")
        + "</body></html>"
    ).encode()

    result = recover_pre2011_official_calendar_sources(
        candidate_registry=_html_registry(
            tmp_path,
            url=url,
            expected_raw=expected_raw,
            expected_text=visible,
        ),
        output=tmp_path / "output",
        session=FakeSession(
            {
                url: FakeResponse(
                    status_code=200,
                    content=drifted_raw,
                    content_type="text/html",
                    url=url,
                )
            }
        ),
    )

    attempt = result.attempts[0]
    assert result.fully_recovered_years == (2009,)
    assert attempt.raw_sha256_match is False
    assert attempt.extracted_text_sha256_match is True
    assert attempt.html_transport_drift_accepted is True
    assert attempt.content_validation_passed is True


def test_official_html_transport_drift_rejects_changed_visible_text(
    tmp_path: Path,
) -> None:
    url = "https://nsearchives.nseindia.com/content/circulars/cmtr12236.htm"
    expected_visible = (
        "National Stock Exchange of India Limited\n"
        "Capital Market Segment\n"
        "Trading holiday on April 30, 2009\n"
        "April 30, 2009 Parliamentary Elections"
    )
    expected_raw = (
        "<html><body>"
        + expected_visible.replace("\n", "<br>")
        + "</body></html>"
    ).encode()
    changed_raw = (
        "<html><head><script>telemetry</script></head><body>"
        "National Stock Exchange of India Limited<br>"
        "Capital Market Segment<br>"
        "Trading holiday on April 30, 2009<br>"
        "May 1, 2009 Changed calendar content"
        "</body></html>"
    ).encode()

    result = recover_pre2011_official_calendar_sources(
        candidate_registry=_html_registry(
            tmp_path,
            url=url,
            expected_raw=expected_raw,
            expected_text=expected_visible,
        ),
        output=tmp_path / "output",
        session=FakeSession(
            {
                url: FakeResponse(
                    status_code=200,
                    content=changed_raw,
                    content_type="text/html",
                    url=url,
                )
            }
        ),
    )

    attempt = result.attempts[0]
    assert result.unrecovered_years == (2009,)
    assert attempt.raw_sha256_match is False
    assert attempt.extracted_text_sha256_match is False
    assert attempt.html_transport_drift_accepted is False
    assert attempt.recovery_state == "OFFICIAL_SOURCE_CONTENT_INVALID"
    assert attempt.error == "SOURCE_DOCUMENT_HASH_MISMATCH"
'''
    if "test_official_html_transport_drift_accepts_identical_visible_text" not in text:
        if marker not in text:
            raise RuntimeError("TEST_INSERTION_MARKER_MISSING")
        text = text.replace(marker, addition + marker, 1)
    TESTS.write_text(text, encoding="utf-8")


def patch_docs() -> None:
    text = DOCS.read_text(encoding="utf-8")
    addition = '''
## Canonical HTML hash boundary

Official NSE archive HTML can receive request-specific telemetry scripts from the
archive delivery layer. The raw response SHA-256 remains recorded. When the pinned
raw hash drifts, recovery is permitted only for an official `.htm`/`.html` URL whose
pinned visible-text SHA-256 is unchanged and whose mandatory circular-content checks
all pass. PDF documents remain raw-byte hash strict. Both hashes and any accepted
HTML transport drift are exported in the recovery attempt ledger.
'''
    if "## Canonical HTML hash boundary" not in text:
        text = text.rstrip() + "\n" + addition
    DOCS.write_text(text, encoding="utf-8")


def main() -> None:
    patch_module()
    patch_registry()
    patch_tests()
    patch_docs()


if __name__ == "__main__":
    main()
