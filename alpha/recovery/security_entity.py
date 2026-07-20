"""Recover canonical security entities with provenance and confidence."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import cast

from .base import CanonicalRecoveryEngine
from .evidence_graph import EvidenceGraph
from .models import (
    CanonicalPreviewRow,
    EvidenceGraphSnapshot,
    EvidenceKind,
    EvidenceNode,
    RecoveryContext,
    RecoveryIssue,
    RecoveryResult,
    RecoverySeverity,
)

_FIELD_ALIASES: Mapping[str, tuple[str, ...]] = {
    "security_id": ("security_id", "instrument_id", "security_code", "scrip_code"),
    "isin": ("isin", "isin_code"),
    "symbol": ("symbol", "ticker", "trading_symbol", "tradingsymbol"),
    "exchange": ("exchange", "exchange_code"),
    "instrument_type": ("instrument_type", "instrument", "series"),
    "listing_date": ("listing_date", "official_listing_date", "listed_on"),
    "delisting_date": (
        "delisting_date",
        "official_delisting_date",
        "delisted_on",
    ),
    "effective_from": ("effective_from", "valid_from", "start_date"),
    "effective_to": ("effective_to", "valid_to", "end_date"),
    "historical_symbols": (
        "historical_symbols",
        "previous_symbols",
        "symbol_history",
    ),
    "corporate_action_lineage": (
        "corporate_action_lineage",
        "lineage",
    ),
}

_SOURCE_WEIGHT = {
    "security_master": 1.0,
    "listing_history": 0.95,
}


class SecurityEntityRecoveryEngine(CanonicalRecoveryEngine):
    """Recover canonical security identity previews from verified raw evidence."""

    engine_key = "security-entity-recovery"
    engine_version = "1.0.0"

    def discover(self, context: RecoveryContext) -> Mapping[str, object]:
        security_master = _required_path(context.parameters, "security_master")
        listing_history = _optional_path(context.parameters, "listing_history")
        master_rows = _read_records(security_master)
        listing_rows = _read_records(listing_history) if listing_history else ()
        return {
            "security_master_path": security_master,
            "listing_history_path": listing_history,
            "security_master_rows": master_rows,
            "listing_history_rows": listing_rows,
        }

    def build_evidence_graph(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
    ) -> EvidenceGraph:
        del context
        graph = EvidenceGraph()
        master_path = cast(Path, discovery["security_master_path"])
        listing_path = cast(Path | None, discovery["listing_history_path"])
        master_rows = _rows(discovery, "security_master_rows")
        listing_rows = _rows(discovery, "listing_history_rows")

        for index, row in enumerate(master_rows):
            graph.add_node(
                EvidenceNode(
                    node_id=f"security_master:{index}",
                    kind=EvidenceKind.RAW_FILE,
                    source="security_master",
                    locator=f"{master_path}#row={index}",
                    attributes=row,
                )
            )
        for index, row in enumerate(listing_rows):
            graph.add_node(
                EvidenceNode(
                    node_id=f"listing_history:{index}",
                    kind=EvidenceKind.RAW_FILE,
                    source="listing_history",
                    locator=f"{listing_path}#row={index}",
                    attributes=row,
                )
            )
        return graph

    def validate(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
    ) -> tuple[RecoveryIssue, ...]:
        del context, graph
        master_rows = _rows(discovery, "security_master_rows")
        issues: list[RecoveryIssue] = []
        if not master_rows:
            issues.append(
                RecoveryIssue(
                    issue_key="empty-security-master",
                    severity=RecoverySeverity.CRITICAL,
                    summary="Security master contains no records.",
                )
            )
            return tuple(issues)

        seen_ids: dict[str, int] = {}
        seen_isins: dict[str, int] = {}
        for index, row in enumerate(master_rows):
            node_id = f"security_master:{index}"
            security_id = _first_value(row, _FIELD_ALIASES["security_id"])
            isin = _first_value(row, _FIELD_ALIASES["isin"])
            symbol = _first_value(row, _FIELD_ALIASES["symbol"])
            if not security_id and not isin:
                issues.append(
                    RecoveryIssue(
                        issue_key=f"missing-identity:{index}",
                        severity=RecoverySeverity.HIGH,
                        summary="Record has neither security_id nor ISIN.",
                        evidence_ids=(node_id,),
                    )
                )
            if not symbol:
                issues.append(
                    RecoveryIssue(
                        issue_key=f"missing-symbol:{index}",
                        severity=RecoverySeverity.MEDIUM,
                        summary="Record has no current symbol.",
                        evidence_ids=(node_id,),
                    )
                )
            _append_duplicate_issue(
                issues,
                seen_ids,
                security_id,
                index,
                "security-id",
                node_id,
            )
            _append_duplicate_issue(
                issues,
                seen_isins,
                isin,
                index,
                "isin",
                node_id,
            )
        return tuple(issues)

    def normalize(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
        validation_issues: tuple[RecoveryIssue, ...],
    ) -> tuple[Mapping[str, object], ...]:
        del context, graph, validation_issues
        master_rows = _rows(discovery, "security_master_rows")
        listing_rows = _rows(discovery, "listing_history_rows")
        listing_index = _index_rows(listing_rows)
        normalized: list[Mapping[str, object]] = []

        for index, master in enumerate(master_rows):
            matches = _matching_rows(master, listing_index)
            sources = [("security_master", f"security_master:{index}", master)]
            sources.extend(
                (
                    "listing_history",
                    f"listing_history:{listing_index[row_key][0]}",
                    listing_index[row_key][1],
                )
                for row_key in matches
            )
            normalized.append(_resolve_entity(sources))
        return tuple(normalized)

    def recover(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
        validation_issues: tuple[RecoveryIssue, ...],
        normalized: tuple[Mapping[str, object], ...],
    ) -> tuple[CanonicalPreviewRow, ...]:
        del context, discovery, graph, validation_issues
        preview: list[CanonicalPreviewRow] = []
        for row in normalized:
            record_key = str(row["record_key"])
            evidence_ids = tuple(cast(Sequence[str], row["evidence_ids"]))
            preview.append(
                CanonicalPreviewRow(
                    record_key=record_key,
                    values=row,
                    evidence_ids=evidence_ids,
                )
            )
        return tuple(sorted(preview, key=lambda item: item.record_key))

    def verify(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
        validation_issues: tuple[RecoveryIssue, ...],
        normalized: tuple[Mapping[str, object], ...],
        preview: tuple[CanonicalPreviewRow, ...],
    ) -> tuple[RecoveryIssue, ...]:
        del context, discovery, validation_issues, normalized
        issues: list[RecoveryIssue] = []
        node_ids = {node.node_id for node in graph.nodes}
        keys: set[str] = set()
        for row in preview:
            if row.record_key in keys:
                issues.append(
                    RecoveryIssue(
                        issue_key=f"duplicate-preview-key:{row.record_key}",
                        severity=RecoverySeverity.HIGH,
                        summary="Canonical preview record key is duplicated.",
                        evidence_ids=row.evidence_ids,
                    )
                )
            keys.add(row.record_key)
            missing = tuple(sorted(set(row.evidence_ids) - node_ids))
            if missing:
                issues.append(
                    RecoveryIssue(
                        issue_key=f"missing-provenance:{row.record_key}",
                        severity=RecoverySeverity.CRITICAL,
                        summary="Canonical preview references missing evidence.",
                        evidence_ids=missing,
                    )
                )
            values = row.values
            confidence = values.get("entity_confidence")
            if not isinstance(confidence, float) or not 0.0 <= confidence <= 1.0:
                issues.append(
                    RecoveryIssue(
                        issue_key=f"invalid-confidence:{row.record_key}",
                        severity=RecoverySeverity.HIGH,
                        summary="Entity confidence is absent or outside [0, 1].",
                        evidence_ids=row.evidence_ids,
                    )
                )
        return tuple(issues)


def export_security_entity_recovery(
    result: RecoveryResult,
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic security-entity recovery preview artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    preview_path = output / "canonical_preview.csv"
    provenance_path = output / "entity_provenance.json"
    confidence_path = output / "confidence_report.csv"
    duplicates_path = output / "duplicates.csv"
    verification_path = output / "verification.json"
    report_path = output / "report.md"

    _write_preview_csv(result.canonical_preview, preview_path)
    provenance_path.write_text(
        json.dumps(
            [
                {
                    "record_key": row.record_key,
                    "evidence_ids": row.evidence_ids,
                    "field_provenance": row.values.get("field_provenance", {}),
                    "field_conflicts": row.values.get("field_conflicts", {}),
                }
                for row in result.canonical_preview
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_confidence_csv(result.canonical_preview, confidence_path)
    _write_issue_csv(
        tuple(
            issue
            for issue in result.validation_issues + result.verification_issues
            if "duplicate" in issue.issue_key
        ),
        duplicates_path,
    )
    verification_path.write_text(
        json.dumps(
            {
                "classification": result.classification,
                "validation_issues": [asdict(item) for item in result.validation_issues],
                "verification_issues": [
                    asdict(item) for item in result.verification_issues
                ],
                "metadata": dict(result.metadata),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path.write_text(_render_report(result), encoding="utf-8")
    return (
        preview_path,
        provenance_path,
        confidence_path,
        duplicates_path,
        verification_path,
        report_path,
    )


def _resolve_entity(
    sources: Sequence[tuple[str, str, Mapping[str, object]]],
) -> Mapping[str, object]:
    resolved: dict[str, object] = {}
    provenance: dict[str, tuple[str, ...]] = {}
    confidence: dict[str, float] = {}
    conflicts: dict[str, tuple[str, ...]] = {}
    all_evidence = tuple(sorted({node_id for _, node_id, _ in sources}))

    for canonical, aliases in _FIELD_ALIASES.items():
        candidates: list[tuple[str, str, object, float]] = []
        for source_name, node_id, row in sources:
            value = _first_object(row, aliases)
            if not _is_null(value):
                candidates.append(
                    (source_name, node_id, value, _SOURCE_WEIGHT[source_name])
                )
        if not candidates:
            resolved[canonical] = None
            provenance[canonical] = ()
            confidence[canonical] = 0.0
            continue
        chosen, supporting, rejected = _choose_candidate(candidates)
        resolved[canonical] = chosen
        provenance[canonical] = tuple(sorted(supporting))
        confidence[canonical] = _field_confidence(candidates, chosen)
        if rejected:
            conflicts[canonical] = tuple(sorted(rejected))

    record_key = str(
        resolved.get("security_id") or resolved.get("isin") or resolved.get("symbol")
    )
    field_scores = tuple(confidence.values())
    entity_confidence = round(sum(field_scores) / len(field_scores), 4)
    return {
        "record_key": record_key,
        **resolved,
        "field_confidence": confidence,
        "field_provenance": provenance,
        "field_conflicts": conflicts,
        "entity_confidence": entity_confidence,
        "evidence_ids": all_evidence,
        "recovery_version": "HTR-002-v1.0.0",
    }


def _choose_candidate(
    candidates: Sequence[tuple[str, str, object, float]],
) -> tuple[object, set[str], set[str]]:
    grouped: dict[str, list[tuple[str, str, object, float]]] = defaultdict(list)
    for candidate in candidates:
        grouped[_render_value(candidate[2])].append(candidate)
    ranked = sorted(
        grouped.values(),
        key=lambda group: (
            -sum(item[3] for item in group),
            -len(group),
            _render_value(group[0][2]),
        ),
    )
    winning = ranked[0]
    chosen = winning[0][2]
    supporting = {item[1] for item in winning}
    rejected = {
        f"{item[1]}={_render_value(item[2])}"
        for group in ranked[1:]
        for item in group
    }
    return chosen, supporting, rejected


def _field_confidence(
    candidates: Sequence[tuple[str, str, object, float]],
    chosen: object,
) -> float:
    chosen_weight = sum(
        weight for _, _, value, weight in candidates if _equal(value, chosen)
    )
    total_weight = sum(weight for _, _, _, weight in candidates)
    agreement = chosen_weight / total_weight if total_weight else 0.0
    source_bonus = min(0.1, 0.05 * (len(candidates) - 1))
    return round(min(1.0, agreement * 0.9 + source_bonus), 4)


def _index_rows(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, tuple[int, Mapping[str, object]]]:
    indexed: dict[str, tuple[int, Mapping[str, object]]] = {}
    for index, row in enumerate(rows):
        for key in _identity_keys(row):
            indexed.setdefault(key, (index, row))
    return indexed


def _matching_rows(
    master: Mapping[str, object],
    index: Mapping[str, tuple[int, Mapping[str, object]]],
) -> tuple[str, ...]:
    return tuple(sorted(key for key in _identity_keys(master) if key in index))[:1]


def _identity_keys(row: Mapping[str, object]) -> tuple[str, ...]:
    keys: list[str] = []
    for field in ("security_id", "isin", "symbol"):
        value = _first_value(row, _FIELD_ALIASES[field])
        if value:
            keys.append(f"{field}:{value.strip().upper()}")
    return tuple(keys)


def _append_duplicate_issue(
    issues: list[RecoveryIssue],
    seen: dict[str, int],
    value: str,
    index: int,
    label: str,
    node_id: str,
) -> None:
    if not value:
        return
    normalized = value.strip().upper()
    previous = seen.get(normalized)
    if previous is not None:
        issues.append(
            RecoveryIssue(
                issue_key=f"duplicate-{label}:{normalized}",
                severity=RecoverySeverity.HIGH,
                summary=f"Duplicate {label} detected.",
                details=f"Rows {previous} and {index} share {normalized}.",
                evidence_ids=(f"security_master:{previous}", node_id),
            )
        )
    else:
        seen[normalized] = index


def _read_records(path: Path) -> tuple[Mapping[str, object], ...]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return tuple(dict(row) for row in csv.DictReader(handle))
    if suffix == ".jsonl":
        payload: object = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    elif suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"unsupported security source: {path}")

    if isinstance(payload, Mapping):
        records = next(
            (
                value
                for value in payload.values()
                if isinstance(value, list)
                and all(isinstance(item, Mapping) for item in value)
            ),
            None,
        )
        payload = records if records is not None else [payload]
    if not isinstance(payload, list) or not all(
        isinstance(item, Mapping) for item in payload
    ):
        raise ValueError(f"security source must contain records: {path}")
    typed_payload = cast(list[Mapping[str, object]], payload)
    return tuple(dict(item) for item in typed_payload)


def _rows(
    discovery: Mapping[str, object],
    key: str,
) -> tuple[Mapping[str, object], ...]:
    value = discovery.get(key)
    if not isinstance(value, tuple) or not all(isinstance(row, Mapping) for row in value):
        raise TypeError(f"{key} must contain mapping records")
    return cast(tuple[Mapping[str, object], ...], value)


def _required_path(parameters: Mapping[str, object], key: str) -> Path:
    value = parameters.get(key)
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value)
    raise ValueError(f"{key} must be a path")


def _optional_path(parameters: Mapping[str, object], key: str) -> Path | None:
    value = parameters.get(key)
    if value is None:
        return None
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value)
    raise ValueError(f"{key} must be a path or None")


def _first_value(row: Mapping[str, object], aliases: Sequence[str]) -> str:
    value = _first_object(row, aliases)
    return "" if _is_null(value) else str(value)


def _first_object(row: Mapping[str, object], aliases: Sequence[str]) -> object:
    normalized = {_normalize(str(key)): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_normalize(alias))
        if not _is_null(value):
            return value
    return None


def _normalize(value: str) -> str:
    return "_".join(
        part for part in value.strip().lower().replace("-", "_").split("_") if part
    )


def _is_null(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _render_value(value: object) -> str:
    if isinstance(value, (Mapping, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _equal(left: object, right: object) -> bool:
    return _render_value(left) == _render_value(right)


def _write_preview_csv(
    rows: Sequence[CanonicalPreviewRow],
    path: Path,
) -> None:
    columns = (
        "record_key",
        "security_id",
        "isin",
        "symbol",
        "exchange",
        "instrument_type",
        "listing_date",
        "delisting_date",
        "effective_from",
        "effective_to",
        "entity_confidence",
        "recovery_version",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {column: row.record_key if column == "record_key" else row.values.get(column)
                 for column in columns}
            )


def _write_confidence_csv(
    rows: Sequence[CanonicalPreviewRow],
    path: Path,
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("record_key", "entity_confidence", "field_confidence"),
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "record_key": row.record_key,
                    "entity_confidence": row.values.get("entity_confidence"),
                    "field_confidence": json.dumps(
                        row.values.get("field_confidence", {}),
                        sort_keys=True,
                    ),
                }
            )


def _write_issue_csv(issues: Sequence[RecoveryIssue], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("issue_key", "severity", "summary", "details", "evidence_ids"),
        )
        writer.writeheader()
        for issue in issues:
            writer.writerow(
                {
                    "issue_key": issue.issue_key,
                    "severity": issue.severity.value,
                    "summary": issue.summary,
                    "details": issue.details,
                    "evidence_ids": "|".join(issue.evidence_ids),
                }
            )


def _render_report(result: RecoveryResult) -> str:
    conflicts = sum(
        len(cast(Mapping[str, object], row.values.get("field_conflicts", {})))
        for row in result.canonical_preview
    )
    return (
        "# Security Entity Recovery\n\n"
        f"- Classification: **{result.classification}**\n"
        f"- Preview rows: `{len(result.canonical_preview)}`\n"
        f"- Evidence nodes: `{len(result.evidence_graph.nodes)}`\n"
        f"- Validation issues: `{len(result.validation_issues)}`\n"
        f"- Verification issues: `{len(result.verification_issues)}`\n"
        f"- Field conflicts: `{conflicts}`\n"
        "- Canonical writes: `False`\n"
    )
