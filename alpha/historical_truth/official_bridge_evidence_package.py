"""Package-level official evidence generation and semantic review for HTR-010B1F."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Any

from alpha.historical_truth.official_bridge_action_evidence import (
    match_corporate_action_file,
)

HTR010B1F_EVIDENCE_PACKAGE_CONTRACT_VERSION = "HTR-010B1F-PACKAGE-v1.1.0"

_REQUIRED_ROLES = ("PRE_IDENTITY", "CORPORATE_ACTION", "POST_IDENTITY")
_ACTION_TERMS = (
    "stock split",
    "face value split",
    "sub-division",
    "subdivision",
    "bonus",
    "consolidation",
    "series",
)


class OfficialBridgeEvidencePackageEngine:
    """Build and semantically review three-document bridge evidence packages."""

    def build_findings(
        self,
        *,
        dossiers_path: Path,
        source_catalog_path: Path,
    ) -> dict[str, Any]:
        dossiers = _records(dossiers_path)
        catalog = _records(source_catalog_path)
        catalog_by_signature = {_signature(row): row for row in catalog}
        findings: list[dict[str, Any]] = []
        package_rows: list[dict[str, Any]] = []

        for dossier in dossiers:
            source = catalog_by_signature.get(_signature(dossier))
            missing_roles: list[str] = []
            if source is None:
                missing_roles = list(_REQUIRED_ROLES)
            else:
                for role, key, source_class in (
                    ("PRE_IDENTITY", "pre_identity_url", "NSE_SECURITY_MASTER"),
                    (
                        "CORPORATE_ACTION",
                        "action_url",
                        "NSE_CORPORATE_ACTION_NOTICE",
                    ),
                    ("POST_IDENTITY", "post_identity_url", "NSE_SECURITY_MASTER"),
                ):
                    source_url = str(source.get(key) or "")
                    if not source_url:
                        missing_roles.append(role)
                        continue
                    findings.append(
                        _finding(
                            dossier=dossier,
                            role=role,
                            source_url=source_url,
                            source_class=source_class,
                        )
                    )
            package_rows.append(
                {
                    "dossier_id": dossier.get("dossier_id"),
                    "symbol": dossier.get("post_symbol") or dossier.get("pre_symbol"),
                    "effective_date": dossier.get("effective_date"),
                    "package_state": (
                        "READY_FOR_GOVERNED_DOWNLOAD"
                        if not missing_roles
                        else "INCOMPLETE_SOURCE_PACKAGE"
                    ),
                    "missing_roles": missing_roles,
                    "production_influence": False,
                }
            )

        package_states = Counter(str(row["package_state"]) for row in package_rows)
        defects = _build_defects(dossiers, catalog, findings)
        report = {
            "contract_version": HTR010B1F_EVIDENCE_PACKAGE_CONTRACT_VERSION,
            "input_dossier_count": len(dossiers),
            "input_catalog_count": len(catalog),
            "generated_document_request_count": len(findings),
            "complete_source_package_count": package_states[
                "READY_FOR_GOVERNED_DOWNLOAD"
            ],
            "incomplete_source_package_count": package_states[
                "INCOMPLETE_SOURCE_PACKAGE"
            ],
            "implementation_defect_count": len(defects),
            "implementation_defects": defects,
            "benchmark_replay_count": 0,
            "production_influence": False,
            "findings": sorted(findings, key=_row_key),
            "packages": sorted(package_rows, key=_row_key),
        }
        report["report_sha256"] = _digest(report)
        return report

    def review_downloaded_packages(
        self,
        *,
        dossiers_path: Path,
        acquisition_discoveries_path: Path,
        downloaded_documents_root: Path,
    ) -> dict[str, Any]:
        dossiers = _records(dossiers_path)
        discoveries = _records(acquisition_discoveries_path)
        by_dossier: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in discoveries:
            by_dossier[str(row.get("dossier_id") or "")].append(row)

        reviewed_rows: list[dict[str, Any]] = []
        package_results: list[dict[str, Any]] = []
        for dossier in dossiers:
            dossier_id = str(dossier.get("dossier_id") or "")
            rows = by_dossier.get(dossier_id, [])
            proof = _package_proof(dossier, rows, downloaded_documents_root)
            continuity = bool(
                proof["pre_identity_proved"]
                and proof["corporate_action_proved"]
                and proof["post_identity_proved"]
            )
            state = (
                "SEMANTICALLY_VERIFIED_CONTINUOUS_IDENTITY"
                if continuity
                else "INSUFFICIENT_SEMANTIC_PACKAGE_EVIDENCE"
            )
            for row in rows:
                reviewed_rows.append(
                    {
                        **row,
                        "identity_continuity_certified": continuity or None,
                        "price_series_continuity_certified": False,
                        "tradability_continuity_certified": False,
                        "semantic_package_state": state,
                        "semantic_package_proof": proof,
                        "production_influence": False,
                    }
                )
            package_results.append(
                {
                    "dossier_id": dossier_id,
                    "symbol": dossier.get("post_symbol") or dossier.get("pre_symbol"),
                    "effective_date": dossier.get("effective_date"),
                    **proof,
                    "identity_continuity_certified": continuity,
                    "semantic_package_state": state,
                    "production_influence": False,
                }
            )

        states = Counter(str(row["semantic_package_state"]) for row in package_results)
        action_states = Counter(
            str(row.get("corporate_action_state") or "UNKNOWN")
            for row in package_results
        )
        defects = _review_defects(dossiers, reviewed_rows, package_results)
        report = {
            "contract_version": HTR010B1F_EVIDENCE_PACKAGE_CONTRACT_VERSION,
            "input_dossier_count": len(dossiers),
            "input_discovery_count": len(discoveries),
            "semantically_verified_package_count": states[
                "SEMANTICALLY_VERIFIED_CONTINUOUS_IDENTITY"
            ],
            "insufficient_semantic_package_count": states[
                "INSUFFICIENT_SEMANTIC_PACKAGE_EVIDENCE"
            ],
            "corporate_action_state_counts": dict(sorted(action_states.items())),
            "pre_identity_proved_count": sum(
                bool(row.get("pre_identity_proved")) for row in package_results
            ),
            "corporate_action_proved_count": sum(
                bool(row.get("corporate_action_proved")) for row in package_results
            ),
            "post_identity_proved_count": sum(
                bool(row.get("post_identity_proved")) for row in package_results
            ),
            "implementation_defect_count": len(defects),
            "implementation_defects": defects,
            "benchmark_replay_count": 0,
            "production_influence": False,
            "reviewed_discoveries": sorted(reviewed_rows, key=_row_key),
            "package_results": sorted(package_results, key=_row_key),
        }
        report["report_sha256"] = _digest(report)
        return report

    @staticmethod
    def export_build(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / "htr010b1f_evidence_package_build.json"
        findings_path = output / "htr010b1f_reviewed_source_findings.json"
        packages_path = output / "htr010b1f_source_packages.json"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        findings_path.write_text(
            json.dumps(report.get("findings", []), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        packages_path.write_text(
            json.dumps(report.get("packages", []), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report_path, findings_path, packages_path

    @staticmethod
    def export_review(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / "htr010b1f_evidence_package_review.json"
        reviewed_path = output / "htr010b1f_semantically_reviewed_discoveries.json"
        packages_path = output / "htr010b1f_semantic_package_results.json"
        diagnostics_path = output / "htr010b1f_action_evidence_diagnostics.json"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        reviewed_path.write_text(
            json.dumps(report.get("reviewed_discoveries", []), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        package_results = report.get("package_results", [])
        packages_path.write_text(
            json.dumps(package_results, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        diagnostics_path.write_text(
            json.dumps(
                [
                    {
                        "dossier_id": row.get("dossier_id"),
                        "symbol": row.get("symbol"),
                        "effective_date": row.get("effective_date"),
                        "corporate_action_state": row.get("corporate_action_state"),
                        "corporate_action_diagnostics": row.get(
                            "corporate_action_diagnostics"
                        ),
                        "unresolved_reasons": row.get("unresolved_reasons"),
                    }
                    for row in package_results
                ],
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return report_path, reviewed_path, packages_path, diagnostics_path


def _finding(
    *,
    dossier: dict[str, Any],
    role: str,
    source_url: str,
    source_class: str,
) -> dict[str, Any]:
    dossier_id = str(dossier.get("dossier_id") or "")
    material = f"{dossier_id}|{role}|{source_url}"
    evidence_id = "htr010b1f-evidence:" + sha256(material.encode()).hexdigest()
    return {
        "dossier_id": dossier_id,
        "evidence_id": evidence_id,
        "document_id": evidence_id,
        "document_date": dossier.get("effective_date"),
        "effective_date": dossier.get("effective_date"),
        "pre_isin": dossier.get("pre_isin"),
        "post_isin": dossier.get("post_isin"),
        "pre_symbol": dossier.get("pre_symbol"),
        "post_symbol": dossier.get("post_symbol"),
        "pre_series": dossier.get("pre_series"),
        "post_series": dossier.get("post_series"),
        "source_class": source_class,
        "source_url": source_url,
        "evidence_role": role,
        "identity_continuity_certified": None,
        "price_series_continuity_certified": False,
        "tradability_continuity_certified": False,
        "production_influence": False,
    }


def _package_proof(
    dossier: dict[str, Any],
    rows: list[dict[str, Any]],
    root: Path,
) -> dict[str, Any]:
    texts: dict[str, list[str]] = defaultdict(list)
    paths: dict[str, list[Path]] = defaultdict(list)
    downloaded_states: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        role = str(row.get("evidence_role") or "")
        downloaded_states[role].append(str(row.get("download_state") or ""))
        if row.get("download_state") != "DOWNLOADED_VERIFIED_BYTES":
            continue
        relative_path = str(row.get("relative_path") or "")
        if not relative_path:
            continue
        path = root / relative_path
        if not path.is_file():
            continue
        paths[role].append(path)
        texts[role].append(path.read_bytes().decode("utf-8", errors="ignore").lower())

    pre_isin = str(dossier.get("pre_isin") or "").lower()
    post_isin = str(dossier.get("post_isin") or "").lower()
    symbol = str(dossier.get("post_symbol") or dossier.get("pre_symbol") or "")
    effective_date = str(dossier.get("effective_date") or "")
    date_tokens = _date_tokens(effective_date)

    pre_proved = bool(
        pre_isin and any(pre_isin in text for text in texts["PRE_IDENTITY"])
    )
    post_proved = bool(
        post_isin and any(post_isin in text for text in texts["POST_IDENTITY"])
    )

    action_diagnostics: list[dict[str, Any]] = []
    action_proved = False
    action_state = "ACTION_DOCUMENT_NOT_DOWNLOADED"
    for path in paths["CORPORATE_ACTION"]:
        if path.suffix.lower() == ".json":
            match = match_corporate_action_file(
                path=path,
                symbol=symbol,
                effective_date=effective_date,
            )
            diagnostic = match.as_dict()
            diagnostic["relative_path"] = path.relative_to(root).as_posix()
            action_diagnostics.append(diagnostic)
            if match.proved:
                action_proved = True
                action_state = match.state
                break
            action_state = match.state
            continue

        text = path.read_bytes().decode("utf-8", errors="ignore").lower()
        legacy_match = bool(
            symbol.lower() in text
            and any(token in text for token in date_tokens)
            and any(term in text for term in _ACTION_TERMS)
        )
        action_diagnostics.append(
            {
                "proved": legacy_match,
                "state": (
                    "LEGACY_ACTION_TEXT_VERIFIED"
                    if legacy_match
                    else "LEGACY_ACTION_TEXT_INSUFFICIENT"
                ),
                "relative_path": path.relative_to(root).as_posix(),
                "payload_sha256": sha256(path.read_bytes()).hexdigest(),
            }
        )
        if legacy_match:
            action_proved = True
            action_state = "LEGACY_ACTION_TEXT_VERIFIED"
            break
        action_state = "LEGACY_ACTION_TEXT_INSUFFICIENT"

    unresolved_reasons: list[str] = []
    if not pre_proved:
        unresolved_reasons.append(
            "MISSING_PRE_IDENTITY_PROOF"
            if paths["PRE_IDENTITY"]
            else "PRE_IDENTITY_DOCUMENT_UNAVAILABLE"
        )
    if not action_proved:
        unresolved_reasons.append(action_state)
    if not post_proved:
        unresolved_reasons.append(
            "MISSING_POST_IDENTITY_PROOF"
            if paths["POST_IDENTITY"]
            else "POST_IDENTITY_DOCUMENT_UNAVAILABLE"
        )

    return {
        "pre_identity_proved": pre_proved,
        "corporate_action_proved": action_proved,
        "post_identity_proved": post_proved,
        "corporate_action_state": action_state,
        "corporate_action_diagnostics": action_diagnostics,
        "unresolved_reasons": unresolved_reasons,
        "downloaded_role_count": sum(bool(paths[role]) for role in _REQUIRED_ROLES),
        "role_download_states": {
            role: downloaded_states.get(role, []) for role in _REQUIRED_ROLES
        },
    }


def _date_tokens(value: str) -> tuple[str, ...]:
    try:
        year, month, day = value.split("-")
    except ValueError:
        return ()
    months = (
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
    )
    month_name = months[int(month) - 1]
    return (
        value.lower(),
        f"{day}-{month}-{year}",
        f"{day}/{month}/{year}",
        f"{day}-{month_name}-{year}",
        f"{day} {month_name} {year}",
    )


def _signature(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("effective_date") or ""),
        str(row.get("pre_isin") or "").upper(),
        str(row.get("post_isin") or "").upper(),
    )


def _build_defects(
    dossiers: tuple[dict[str, Any], ...],
    catalog: tuple[dict[str, Any], ...],
    findings: list[dict[str, Any]],
) -> list[str]:
    defects: list[str] = []
    if len(dossiers) != 20:
        defects.append(f"EXPECTED_20_DOSSIERS_FOUND_{len(dossiers)}")
    if len(catalog) != 20:
        defects.append(f"EXPECTED_20_CATALOG_ROWS_FOUND_{len(catalog)}")
    if len({_signature(row) for row in catalog}) != len(catalog):
        defects.append("DUPLICATE_SOURCE_CATALOG_SIGNATURE")
    if any(row.get("production_influence") is True for row in findings):
        defects.append("PRODUCTION_INFLUENCE_TRUE")
    return defects


def _review_defects(
    dossiers: tuple[dict[str, Any], ...],
    reviewed: list[dict[str, Any]],
    packages: list[dict[str, Any]],
) -> list[str]:
    defects: list[str] = []
    if len(dossiers) != 20:
        defects.append(f"EXPECTED_20_DOSSIERS_FOUND_{len(dossiers)}")
    if len(packages) != len(dossiers):
        defects.append("PACKAGE_RESULT_COUNT_MISMATCH")
    if any(row.get("production_influence") is True for row in reviewed + packages):
        defects.append("PRODUCTION_INFLUENCE_TRUE")
    return defects


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return tuple(row for row in payload if isinstance(row, dict))
    if isinstance(payload, dict):
        for key in (
            "dossiers",
            "records",
            "rows",
            "discoveries",
            "reviewed_discoveries",
        ):
            rows = payload.get(key)
            if isinstance(rows, list):
                return tuple(row for row in rows if isinstance(row, dict))
    raise ValueError(f"unsupported record payload: {path}")


def _row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("dossier_id") or ""),
        str(row.get("evidence_role") or ""),
        str(row.get("document_id") or ""),
    )


def _digest(report: dict[str, Any]) -> str:
    payload = {**report, "report_sha256": ""}
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = [
    "HTR010B1F_EVIDENCE_PACKAGE_CONTRACT_VERSION",
    "OfficialBridgeEvidencePackageEngine",
]
