"""Deterministic artifacts and public verification for DSI-013 source readiness."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Final

from alpha.decision_superiority.intraday_execution_models import (
    DSI013_RESEARCH_SCOPE,
    IntradayExecutionError,
)
from alpha.decision_superiority.intraday_source_certification import (
    DSI013_SOURCE_CONTRACT_VERSION,
    IntradaySourceCertificationResult,
    source_governance_flags,
)

DSI013_SOURCE_CERTIFICATE = "dsi013_intraday_source_certificate.json"
DSI013_SOURCE_REPORT = "dsi013_intraday_source_report.md"
DSI013_SOURCE_ARTIFACTS: Final[dict[str, str]] = {
    "source_contract": "dsi013_source_contract_snapshot.csv",
    "candidate_population": "dsi013_candidate_population.csv",
    "request_plan": "dsi013_intraday_request_plan.csv",
    "identity_resolution": "dsi013_identity_resolution.csv",
    "bar_validation": "dsi013_bar_validation.csv",
    "session_validation": "dsi013_session_validation.csv",
    "daily_reconciliation": "dsi013_daily_reconciliation.csv",
    "source_exclusions": "dsi013_source_exclusions.csv",
    "population_reconciliation": "dsi013_population_reconciliation.csv",
}


def export_intraday_source_certification(
    result: IntradaySourceCertificationResult,
    output: Path,
) -> tuple[Path, ...]:
    """Write and hash-bind the complete deterministic source package."""

    output.mkdir(parents=True, exist_ok=True)
    support: list[Path] = []
    for key, filename in DSI013_SOURCE_ARTIFACTS.items():
        rows = result.rows.get(key)
        if rows is None:
            raise IntradayExecutionError(f"DSI013_SOURCE_ROWS_MISSING:{key}")
        support.append(_write_csv(output / filename, rows))
    report = _write_text(output / DSI013_SOURCE_REPORT, _report(result))
    support.append(report)
    manifest = {
        path.name: _sha256(path) for path in sorted(support, key=lambda item: item.name)
    }
    payload: dict[str, Any] = {
        "contract_version": DSI013_SOURCE_CONTRACT_VERSION,
        "research_scope": DSI013_RESEARCH_SCOPE,
        "source_commit": result.source_commit,
        "readiness_decision": result.readiness.value,
        "blockers": list(result.blockers),
        "summary": dict(result.summaries),
        "support_artifact_manifest": dict(sorted(manifest.items())),
        "executive_report_sha256": _sha256(report),
        "governance_flags": dict(result.governance),
        "automatic_promotion_count": 0,
    }
    payload["report_sha256"] = _canonical_payload_sha256(payload)
    certificate = _write_json(output / DSI013_SOURCE_CERTIFICATE, payload)
    return (certificate, *sorted(support, key=lambda path: path.name))


def validate_intraday_source_certificate(
    certificate: Path,
    *,
    require_ready: bool = False,
) -> dict[str, Any]:
    """Validate certificate payload, support hashes, and source guardrails."""

    payload = _read_json(certificate)
    if payload.get("contract_version") != DSI013_SOURCE_CONTRACT_VERSION:
        raise IntradayExecutionError("UNSUPPORTED_DSI013_SOURCE_CONTRACT")
    if payload.get("research_scope") != DSI013_RESEARCH_SCOPE:
        raise IntradayExecutionError("DSI013_SOURCE_RESEARCH_SCOPE_MISMATCH")
    if payload.get("governance_flags") != source_governance_flags():
        raise IntradayExecutionError("DSI013_SOURCE_GOVERNANCE_FLAGS_INVALID")
    if payload.get("report_sha256") != _canonical_payload_sha256(payload):
        raise IntradayExecutionError("DSI013_SOURCE_CERTIFICATE_PAYLOAD_TAMPERED")
    manifest = payload.get("support_artifact_manifest")
    expected = frozenset((*DSI013_SOURCE_ARTIFACTS.values(), DSI013_SOURCE_REPORT))
    if not isinstance(manifest, dict) or frozenset(manifest) != expected:
        raise IntradayExecutionError("DSI013_SOURCE_SUPPORT_MANIFEST_INVALID")
    root = certificate.resolve().parent
    for name, digest in sorted(manifest.items()):
        path = (root / str(name)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise IntradayExecutionError("DSI013_SOURCE_SUPPORT_PATH_UNSAFE")
        if _sha256(path) != str(digest):
            raise IntradayExecutionError(f"DSI013_SOURCE_ARTIFACT_TAMPERED:{name}")
        content = path.read_bytes()
        if b"Bearer " in content or b"Authorization" in content:
            raise IntradayExecutionError(
                f"DSI013_SOURCE_CREDENTIAL_LEAK:{name}"
            )
        if b"/Users/" in content:
            raise IntradayExecutionError(
                f"DSI013_SOURCE_MACHINE_LOCAL_PATH_LEAK:{name}"
            )
    report = root / DSI013_SOURCE_REPORT
    if payload.get("executive_report_sha256") != _sha256(report):
        raise IntradayExecutionError("DSI013_SOURCE_REPORT_HASH_MISMATCH")
    if payload.get("automatic_promotion_count") != 0:
        raise IntradayExecutionError("DSI013_SOURCE_AUTOMATIC_PROMOTION")
    readiness = str(payload.get("readiness_decision") or "")
    if require_ready and readiness != "READY_FOR_GOVERNED_INTRADAY_SOURCE_RESEARCH":
        raise IntradayExecutionError(f"DSI013_SOURCE_NOT_READY:{readiness}")
    return payload


def _report(result: IntradaySourceCertificationResult) -> str:
    summary = result.summaries
    lines = [
        "# DSI-013 Governed Intraday Source Certification",
        "",
        "## Decision",
        "",
        f"- Contract: `{DSI013_SOURCE_CONTRACT_VERSION}`",
        f"- Readiness: `{result.readiness.value}`",
        f"- Candidates: {summary['candidate_count']}",
        f"- Unique identity/session requests: {summary['request_count']}",
        f"- Admitted requests: {summary['admitted_request_count']}",
        f"- Identity failures: {summary['identity_failure_count']}",
        f"- Source-unavailable requests: {summary['source_unavailable_count']}",
        f"- Session-integrity failures: {summary['session_failure_count']}",
        (
            "- Daily reconciliation failures: "
            f"{summary['reconciliation_failure_count']}"
        ),
        f"- Blockers: {summary['blocker_count']}",
        "",
        "## Interpretation",
        "",
    ]
    if result.readiness.value == "READY_FOR_GOVERNED_INTRADAY_SOURCE_RESEARCH":
        lines.extend(
            [
                "The candidate-bounded five-minute source is ready for governed ",
                "entry-mechanism research. This certifies source identity and ",
                "session evidence only; it does not validate an intraday strategy.",
            ]
        )
    else:
        lines.extend(
            [
                "The source remains fail-closed. No intraday entry mechanism or ",
                "performance conclusion may be evaluated from this package.",
            ]
        )
    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- `VALIDATED_STRATEGY=false`",
            "- `INTRADAY_LIVE_TRADING_ENABLED=false`",
            "- `AUTOMATIC_STRATEGY_PROMOTION_ENABLED=false`",
            "- `PRODUCTION_INFLUENCE=false`",
            "",
        ]
    )
    return "\n".join(lines)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    if not rows:
        return _write_text(path, "")
    fields = sorted({str(field) for row in rows for field in row})
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _scalar(row.get(field)) for field in fields})
    return _write_text(path, stream.getvalue())


def _scalar(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping | list | tuple):
        return json.dumps(_normalise(value), separators=(",", ":"), sort_keys=True)
    return value


def _normalise(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalise(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_normalise(item) for item in value]
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def _canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    normalized = {key: value for key, value in payload.items() if key != "report_sha256"}
    encoded = json.dumps(
        _normalise(normalized),
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise IntradayExecutionError("DSI013_SOURCE_CERTIFICATE_MISSING")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IntradayExecutionError("DSI013_SOURCE_CERTIFICATE_UNREADABLE") from exc
    if not isinstance(value, dict):
        raise IntradayExecutionError("DSI013_SOURCE_CERTIFICATE_SCHEMA_INVALID")
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    content = json.dumps(_normalise(payload), indent=2, sort_keys=True) + "\n"
    return _write_text(path, content)


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "DSI013_SOURCE_ARTIFACTS",
    "DSI013_SOURCE_CERTIFICATE",
    "DSI013_SOURCE_REPORT",
    "export_intraday_source_certification",
    "validate_intraday_source_certificate",
]
