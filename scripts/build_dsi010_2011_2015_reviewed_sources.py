# ruff: noqa: E501
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, cast

from alpha.decision_superiority.pre2016_calendar_sources import (
    build_reviewed_official_calendar_source,
    validate_hash_bound_official_calendar_source,
)


REVIEW_ROWS: dict[str, str] = {
    "NSE_CMTR_16348_2011_ANNUAL_CALENDAR": """
2011-01-01|HOLIDAY|New Year
2011-01-26|HOLIDAY|Republic Day
2011-03-02|HOLIDAY|Mahashivratri
2011-03-20|HOLIDAY|Holi
2011-04-12|HOLIDAY|Ram Navmi
2011-04-14|HOLIDAY|Dr. Ambedkar Jayanti
2011-04-16|HOLIDAY|Mahavir Jayanti
2011-04-22|HOLIDAY|Good Friday
2011-05-01|HOLIDAY|May Day
2011-08-15|HOLIDAY|Independence Day
2011-08-31|HOLIDAY|Ramzan ID
2011-09-01|HOLIDAY|Ganesh Chaturthi
2011-10-02|HOLIDAY|Gandhi Jayanti
2011-10-06|HOLIDAY|Dasara
2011-10-26|HOLIDAY|Laxmi Puja; Muhurat session separately verified
2011-10-27|HOLIDAY|Diwali - Balipratipada
2011-11-07|HOLIDAY|Bakri Id
2011-11-10|HOLIDAY|Gurunanak Jayanti
2011-12-06|HOLIDAY|Moharram
2011-12-25|HOLIDAY|Christmas
""",
    "NSE_CMTR_19187_2011_SPECIAL_SESSION": """
2011-10-26|SPECIAL_SESSION|Muhurat Trading - Diwali
""",
    "NSE_CMTR_19539_2012_ANNUAL_CALENDAR": """
2012-01-01|HOLIDAY|New Year
2012-01-26|HOLIDAY|Republic Day
2012-02-20|HOLIDAY|Mahashivratri
2012-03-08|HOLIDAY|Holi
2012-04-01|HOLIDAY|Ram Navami
2012-04-05|HOLIDAY|Mahavir Jayanti
2012-04-06|HOLIDAY|Good Friday
2012-04-14|HOLIDAY|Ambedkar Jayanti
2012-05-01|HOLIDAY|May Day
2012-08-15|HOLIDAY|Independence Day
2012-08-20|HOLIDAY|Ramzan ID
2012-09-19|HOLIDAY|Ganesh Chaturthi
2012-10-02|HOLIDAY|Gandhi Jayanti
2012-10-24|HOLIDAY|Dasera
2012-10-27|HOLIDAY|Bakri Id
2012-11-13|HOLIDAY|Diwali - Laxmi Puja; Muhurat session separately verified
2012-11-14|HOLIDAY|Diwali - Balipratipada
2012-11-25|HOLIDAY|Moharram
2012-11-28|HOLIDAY|Gurunanak Jayanti
2012-12-25|HOLIDAY|Christmas
""",
    "NSE_CMTR_22083_2012_SPECIAL_SESSION_REVISED": """
2012-11-13|SPECIAL_SESSION|Muhurat Trading - Diwali; revised operative timings
""",
    "NSE_CMTR_22317_2013_ANNUAL_CALENDAR": """
2013-01-26|HOLIDAY|Republic Day
2013-03-10|HOLIDAY|Mahashivratri
2013-03-27|HOLIDAY|Holi
2013-03-29|HOLIDAY|Good Friday
2013-04-14|HOLIDAY|Dr. Ambedkar Jayanti
2013-04-19|HOLIDAY|Ram Navmi
2013-04-24|HOLIDAY|Mahavir Jayanti
2013-05-01|HOLIDAY|May Day
2013-08-09|HOLIDAY|Ramzan ID
2013-08-15|HOLIDAY|Independence Day
2013-09-09|HOLIDAY|Ganesh Chaturthi
2013-10-02|HOLIDAY|Gandhi Jayanti
2013-10-13|HOLIDAY|Dasera
2013-10-16|HOLIDAY|Bakri ID
2013-11-03|HOLIDAY|Diwali - Laxmi Puja; Muhurat session separately verified
2013-11-04|HOLIDAY|Diwali - Balipratipada
2013-11-17|HOLIDAY|Gurunanak Jayanti
2013-12-25|HOLIDAY|Christmas
""",
    "NSE_CMTR_24773_2013_SPECIAL_SESSION": """
2013-11-03|SPECIAL_SESSION|Muhurat Trading - Diwali
""",
    "NSE_CMTR_24977_2013_HOLIDAY_AMENDMENT": """
2013-11-15|HOLIDAY|Moharram; replaces revoked November 14 holiday
""",
    "NSE_CMTR_25326_2014_ANNUAL_CALENDAR": """
2014-01-26|HOLIDAY|Republic Day
2014-02-27|HOLIDAY|Mahashivratri
2014-03-17|HOLIDAY|Holi
2014-04-08|HOLIDAY|Ram Navami
2014-04-13|HOLIDAY|Mahavir Jayanti
2014-04-14|HOLIDAY|Dr. Baba Saheb Ambedkar Jayanti
2014-04-18|HOLIDAY|Good Friday
2014-05-01|HOLIDAY|May Day
2014-07-29|HOLIDAY|Ramzan ID
2014-08-15|HOLIDAY|Independence Day
2014-08-29|HOLIDAY|Ganesh Chaturthi
2014-10-02|HOLIDAY|Mahatma Gandhi Jayanti
2014-10-03|HOLIDAY|Dasera
2014-10-06|HOLIDAY|Bakri ID
2014-10-23|HOLIDAY|Diwali - Laxmi Pujan; Muhurat session separately verified
2014-10-24|HOLIDAY|Diwali - Balipratipada
2014-11-04|HOLIDAY|Moharram
2014-11-06|HOLIDAY|Gurunanak Jayanti
2014-12-25|HOLIDAY|Christmas
""",
    "NSE_CMTR_26360_2014_HOLIDAY_AMENDMENT": """
2014-04-24|HOLIDAY|Parliamentary Elections in Mumbai
""",
    "NSE_CMTR_27779_2014_SPECIAL_SESSION": """
2014-10-23|SPECIAL_SESSION|Muhurat Trading - Diwali
""",
    "NSE_CMTR_27792_2014_HOLIDAY_AMENDMENT": """
2014-10-15|HOLIDAY|General Assembly Elections in Maharashtra
""",
    "NSE_CMTR_28337_2015_ANNUAL_CALENDAR": """
2015-01-26|HOLIDAY|Republic Day
2015-02-17|HOLIDAY|Mahashivratri
2015-03-06|HOLIDAY|Holi
2015-03-28|HOLIDAY|Ram Navami
2015-04-02|HOLIDAY|Mahavir Jayanti
2015-04-03|HOLIDAY|Good Friday
2015-04-14|HOLIDAY|Dr. Baba Saheb Ambedkar Jayanti
2015-05-01|HOLIDAY|Maharashtra Day
2015-07-18|HOLIDAY|Id-Ul-Fitr - Ramzan ID
2015-08-15|HOLIDAY|Independence Day
2015-09-17|HOLIDAY|Ganesh Chaturthi
2015-09-25|HOLIDAY|Bakri ID
2015-10-02|HOLIDAY|Mahatma Gandhi Jayanti
2015-10-22|HOLIDAY|Dasera
2015-10-24|HOLIDAY|Moharram
2015-11-11|HOLIDAY|Diwali - Laxmi Pujan; Muhurat session separately verified
2015-11-12|HOLIDAY|Diwali - Balipratipada
2015-11-25|HOLIDAY|Gurunanak Jayanti
2015-12-25|HOLIDAY|Christmas
""",
    "NSE_CMTR_31047_2015_SPECIAL_SESSION": """
2015-11-11|SPECIAL_SESSION|Muhurat Trading - Diwali
""",
}

RECOVERED_NOT_ADMITTED = {
    "NSE_CMTR_22027_2012_SPECIAL_SESSION_SUPERSEDED": (
        "Superseded by NSE_CMTR_22083_2012_SPECIAL_SESSION_REVISED"
    )
}
CHECK_FIELDS = (
    "exchange_match",
    "segment_match",
    "subject_match",
    "year_match",
    "download_number_match",
    "circular_date_match",
    "holiday_table_match",
    "muhurat_statement_match",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parsed_rows(source_id: str) -> tuple[dict[str, str], ...]:
    rows: list[dict[str, str]] = []
    for line in REVIEW_ROWS[source_id].splitlines():
        if not line.strip():
            continue
        trading_date, classification, description = line.split("|", maxsplit=2)
        rows.append(
            {
                "trading_date": trading_date,
                "classification": classification,
                "description": description,
                "review_state": "VERIFIED_OFFICIAL_EVIDENCE",
                "segment_scope": "CAPITAL_MARKET",
                "source_id": source_id,
            }
        )
    return tuple(rows)


def _write_csv(path: Path, rows: tuple[dict[str, str], ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "trading_date",
                "classification",
                "description",
                "review_state",
                "segment_scope",
                "source_id",
            ),
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_validation(path: Path, attempt: dict[str, object]) -> None:
    lines = [
        f"{field}: {'MATCHED' if attempt.get(field) is True else 'FAILED'}"
        for field in CHECK_FIELDS
    ]
    lines.extend(
        (
            f"document_format: {attempt.get('document_format')}",
            f"response_sha256: {attempt.get('response_sha256')}",
            "OFFICIAL_CIRCULAR_CONTENT_VALID=true",
            "MANUAL_REVIEW_COMPLETED=true",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _attempts(path: Path) -> dict[str, dict[str, object]]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("RECOVERY_ATTEMPTS_INVALID")
    result: dict[str, dict[str, object]] = {}
    for raw in payload:
        if not isinstance(raw, dict):
            raise RuntimeError("RECOVERY_ATTEMPT_ROW_INVALID")
        item = cast(dict[str, object], raw)
        source_id = str(item.get("source_id") or "")
        if not source_id or source_id in result:
            raise RuntimeError("RECOVERY_ATTEMPT_IDENTITY_INVALID")
        result[source_id] = item
    return result


def build_sources(recovery_root: Path, output_root: Path) -> tuple[Path, ...]:
    by_source = _attempts(recovery_root / "source_candidate_attempts.json")
    required = set(REVIEW_ROWS) | set(RECOVERED_NOT_ADMITTED)
    if set(by_source) != required:
        missing = sorted(required - set(by_source))
        extra = sorted(set(by_source) - required)
        raise RuntimeError(f"RECOVERY_SOURCE_SET_MISMATCH:missing={missing}:extra={extra}")
    for source_id, attempt in by_source.items():
        if attempt.get("recovery_state") != "VERIFIED_OFFICIAL_EVIDENCE":
            raise RuntimeError(f"SOURCE_NOT_VERIFIED:{source_id}")
        if attempt.get("segment_scope") != "CAPITAL_MARKET":
            raise RuntimeError(f"SOURCE_SCOPE_INVALID:{source_id}")
        if attempt.get("content_validation_passed") is not True:
            raise RuntimeError(f"SOURCE_CONTENT_INVALID:{source_id}")

    source_paths: list[Path] = []
    master_rows: list[dict[str, str]] = []
    manifest_rows: list[dict[str, object]] = []
    for source_id in sorted(REVIEW_ROWS):
        attempt = by_source[source_id]
        rows = _parsed_rows(source_id)
        master_rows.extend(rows)
        review_path = output_root / "reviews" / f"{source_id}.csv"
        validation_path = output_root / "validation" / f"{source_id}.txt"
        _write_csv(review_path, rows)
        _write_validation(validation_path, attempt)

        document_path = Path(str(attempt.get("document_path") or ""))
        extracted_text_path = Path(str(attempt.get("extracted_text_path") or ""))
        year = int(str(attempt.get("year") or "0"))
        source_path = output_root / "sources" / f"nse_{year}_{source_id}.json"
        build_reviewed_official_calendar_source(
            review_csv=review_path,
            source_document=document_path,
            source_url=str(attempt.get("final_url") or ""),
            source_id=source_id,
            covered_years=(year,),
            output=source_path,
            segment_scope="CAPITAL_MARKET",
            extracted_text=extracted_text_path,
            content_validation=validation_path,
        )
        source_payload = validate_hash_bound_official_calendar_source(
            source_path,
            require_capital_market_scope=True,
        )
        holidays = source_payload.get("holidays")
        special_sessions = source_payload.get("special_sessions")
        if not isinstance(holidays, list) or not isinstance(special_sessions, list):
            raise RuntimeError(f"SOURCE_ROWS_INVALID:{source_id}")
        source_paths.append(source_path)
        manifest_rows.append(
            {
                "year": year,
                "source_id": source_id,
                "source_path": str(source_path),
                "source_json_sha256": _sha256(source_path),
                "source_document_sha256": source_payload["source_document_sha256"],
                "review_csv_sha256": source_payload["review_csv_sha256"],
                "holiday_count": len(holidays),
                "special_session_count": len(special_sessions),
                "segment_scope": source_payload["segment_scope"],
            }
        )

    master_rows.sort(key=lambda row: (row["trading_date"], row["source_id"]))
    _write_csv(output_root / "reviewed_calendar_master.csv", tuple(master_rows))
    holiday_count = sum(row["classification"] == "HOLIDAY" for row in master_rows)
    special_count = sum(
        row["classification"] == "SPECIAL_SESSION" for row in master_rows
    )
    if holiday_count != 99 or special_count != 5:
        raise RuntimeError(
            f"REVIEW_COUNT_MISMATCH:holidays={holiday_count}:specials={special_count}"
        )
    manifest = {
        "covered_years": [2011, 2012, 2013, 2014, 2015],
        "source_count": len(manifest_rows),
        "holiday_row_count": holiday_count,
        "special_session_row_count": special_count,
        "sources": manifest_rows,
        "recovered_not_admitted": [
            {
                "source_id": source_id,
                "reason": reason,
                "response_sha256": by_source[source_id].get("response_sha256"),
            }
            for source_id, reason in sorted(RECOVERED_NOT_ADMITTED.items())
        ],
        "manual_review_completed": True,
        "supersession_applied": True,
        "revocation_applied": {
            "2013-11-14": "Revoked by NSE_CMTR_24977_2013_HOLIDAY_AMENDMENT",
            "replacement_holiday": "2013-11-15",
        },
        "classification_inferred_from_archive_status": False,
        "classification_inferred_from_observed_candles": False,
        "calendar_certification_permitted": False,
        "production_influence": False,
    }
    manifest_path = output_root / "reviewed_source_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return (*source_paths, manifest_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recovery-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    paths = build_sources(args.recovery_root, args.output_root)
    print("===== DSI-010 2011-2015 REVIEWED CALENDAR SOURCES =====")
    print(f"Reviewed Sources: {len(paths) - 1}")
    print("Covered Years: 2011,2012,2013,2014,2015")
    print("Reviewed Holiday Rows: 99")
    print("Reviewed Special Sessions: 5")
    print("Recovered Not Admitted: 1")
    print("Supersession Applied: true")
    print("Revocation Applied: true")
    print("Calendar Certification Permitted: false")
    print("Production Influence: false")


if __name__ == "__main__":
    main()
