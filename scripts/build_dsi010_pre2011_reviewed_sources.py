# ruff: noqa: E501
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from alpha.decision_superiority.pre2016_calendar_sources import (
    build_reviewed_official_calendar_source,
    validate_hash_bound_official_calendar_source,
)


REVIEW_ROWS: dict[str, str] = {
    "NSE_CMTR_5633_2005_ANNUAL_CALENDAR": """
2005-01-21|HOLIDAY|Bakri Id
2005-01-26|HOLIDAY|Republic Day
2005-02-20|HOLIDAY|Moharram
2005-03-25|HOLIDAY|Good Friday
2005-03-26|HOLIDAY|Holi
2005-04-14|HOLIDAY|Ambedkar Jayanti
2005-05-01|HOLIDAY|Maharashtra Day
2005-08-15|HOLIDAY|Independence Day
2005-09-07|HOLIDAY|Ganesh Chaturthi
2005-10-02|HOLIDAY|Gandhi Jayanti
2005-10-12|HOLIDAY|Dasara
2005-11-01|HOLIDAY|Laxmi Puja; Muhurat session separately verified
2005-11-03|HOLIDAY|Bhaubeej
2005-11-05|HOLIDAY|Ramzan Id; superseded by 2005-11-04 amendment
2005-11-15|HOLIDAY|Guru Nanak Jayanti
2005-12-25|HOLIDAY|Christmas
""",
    "NSE_CMTR_6787_2005_HOLIDAY_AMENDMENT": """
2005-11-04|HOLIDAY|Ramzan Id; amended from Saturday 2005-11-05
""",
    "NSE_CMTR_6793_2005_SPECIAL_SESSION": """
2005-11-01|SPECIAL_SESSION|Muhurat Trading - Diwali
""",
    "NSE_CMTR_6946_2006_ANNUAL_CALENDAR": """
2006-01-11|HOLIDAY|Bakri Id
2006-01-26|HOLIDAY|Republic Day
2006-02-09|HOLIDAY|Moharram
2006-03-15|HOLIDAY|Holi
2006-04-06|HOLIDAY|Ram Navami
2006-04-11|HOLIDAY|Mahavir Jayanti / Id-E-Milad
2006-04-14|HOLIDAY|Ambedkar Jayanti / Good Friday
2006-05-01|HOLIDAY|Maharashtra Day
2006-05-13|HOLIDAY|Buddha Pournima
2006-08-15|HOLIDAY|Independence Day
2006-08-27|HOLIDAY|Ganesh Chaturthi
2006-10-02|HOLIDAY|Gandhi Jayanti / Dasara
2006-10-21|HOLIDAY|Laxmi Puja; Muhurat session separately verified
2006-10-24|HOLIDAY|Bhaubeej
2006-10-25|HOLIDAY|Ramzan Id
2006-11-05|HOLIDAY|Guru Nanak Jayanti
2006-12-25|HOLIDAY|Christmas
""",
    "NSE_CMTR_7977_2006_SPECIAL_SESSION": """
2006-10-21|SPECIAL_SESSION|Muhurat Trading - Diwali
""",
    "NSE_CMTR_8182_2007_ANNUAL_CALENDAR": """
2007-01-01|HOLIDAY|Bakri Id
2007-01-26|HOLIDAY|Republic Day
2007-01-30|HOLIDAY|Moharram
2007-02-16|HOLIDAY|Mahashivratri
2007-03-04|HOLIDAY|Holi
2007-03-27|HOLIDAY|Ram Navami
2007-03-31|HOLIDAY|Mahavir Jayanti
2007-04-01|HOLIDAY|Id-E-Milad
2007-04-06|HOLIDAY|Good Friday
2007-04-14|HOLIDAY|Ambedkar Jayanti
2007-05-01|HOLIDAY|Maharashtra Day
2007-05-02|HOLIDAY|Buddha Pournima
2007-08-15|HOLIDAY|Independence Day
2007-09-15|HOLIDAY|Ganesh Chaturthi
2007-10-02|HOLIDAY|Gandhi Jayanti
2007-10-14|HOLIDAY|Ramzan Id
2007-10-21|HOLIDAY|Dasara
2007-11-09|HOLIDAY|Laxmi Puja; Muhurat session separately verified
2007-11-11|HOLIDAY|Bhaubeej
2007-11-24|HOLIDAY|Guru Nanak Jayanti
2007-12-21|HOLIDAY|Bakri Id; second occurrence in 2007
2007-12-25|HOLIDAY|Christmas
""",
    "NSE_CMTR_9666_2007_SPECIAL_SESSION": """
2007-11-09|SPECIAL_SESSION|Muhurat Trading - Diwali
""",
    "NSE_CMTR_9908_2008_ANNUAL_CALENDAR": """
2008-01-19|HOLIDAY|Moharram
2008-01-26|HOLIDAY|Republic Day
2008-03-06|HOLIDAY|Mahashivratri
2008-03-20|HOLIDAY|Id-E-Milad
2008-03-21|HOLIDAY|Good Friday
2008-03-22|HOLIDAY|Holi
2008-04-13|HOLIDAY|Ram Navmi
2008-04-14|HOLIDAY|Dr. Babasaheb Ambedkar Jayanti
2008-04-18|HOLIDAY|Mahavir Jayanti
2008-05-01|HOLIDAY|Maharashtra Day
2008-05-19|HOLIDAY|Buddha Pournima
2008-08-15|HOLIDAY|Independence Day
2008-09-03|HOLIDAY|Ganesh Chaturthi
2008-10-02|HOLIDAY|Gandhi Jayanti / Ramzan Id
2008-10-09|HOLIDAY|Dasara
2008-10-28|HOLIDAY|Laxmi Puja; Muhurat session separately verified
2008-10-30|HOLIDAY|Bhau Bhij
2008-11-13|HOLIDAY|Gurunanak Jayanti
2008-12-09|HOLIDAY|Bakri Id
2008-12-25|HOLIDAY|Christmas
""",
    "NSE_CMTR_11371_2008_SPECIAL_SESSION": """
2008-10-28|SPECIAL_SESSION|Muhurat Trading - Diwali
""",
    "NSE_CMTR_11733_2009_ANNUAL_CALENDAR": """
2009-01-08|HOLIDAY|Moharram
2009-01-26|HOLIDAY|Republic Day
2009-02-23|HOLIDAY|Mahashivratri
2009-03-10|HOLIDAY|Id-E-Milad
2009-03-11|HOLIDAY|Holi
2009-04-03|HOLIDAY|Ram Navmi
2009-04-07|HOLIDAY|Mahavir Jayanti
2009-04-10|HOLIDAY|Good Friday
2009-04-14|HOLIDAY|Dr. Ambedkar Jayanti
2009-05-01|HOLIDAY|Maharashtra Day
2009-05-09|HOLIDAY|Buddha Pournima
2009-08-15|HOLIDAY|Independence Day
2009-08-23|HOLIDAY|Ganesh Chaturthi
2009-09-21|HOLIDAY|Ramzan Id
2009-09-28|HOLIDAY|Dasara
2009-10-02|HOLIDAY|Gandhi Jayanti
2009-10-17|HOLIDAY|Laxmi Puja; Muhurat session separately verified
2009-10-19|HOLIDAY|Bhau Bhij
2009-11-02|HOLIDAY|Gurunanak Jayanti
2009-11-28|HOLIDAY|Bakri Id
2009-12-25|HOLIDAY|Christmas
2009-12-28|HOLIDAY|Moharram; second occurrence in 2009
""",
    "NSE_CMTR_12236_2009_HOLIDAY_AMENDMENT": """
2009-04-30|HOLIDAY|Parliamentary Elections in Mumbai
""",
    "NSE_CMTR_13174_2009_SPECIAL_SESSION": """
2009-10-17|SPECIAL_SESSION|Muhurat Trading - Diwali
""",
    "NSE_CMTR_13194_2009_HOLIDAY_AMENDMENT": """
2009-10-13|HOLIDAY|Assembly Elections in Maharashtra
""",
    "NSE_CMTR_13713_2010_ANNUAL_CALENDAR": """
2010-01-01|HOLIDAY|New Year
2010-01-26|HOLIDAY|Republic Day
2010-02-12|HOLIDAY|Mahashivratri
2010-03-01|HOLIDAY|Holi
2010-03-24|HOLIDAY|Ram Navmi
2010-03-28|HOLIDAY|Mahavir Jayanti
2010-04-02|HOLIDAY|Good Friday
2010-04-14|HOLIDAY|Dr. Ambedkar Jayanti
2010-05-01|HOLIDAY|May Day
2010-08-15|HOLIDAY|Independence Day
2010-09-10|HOLIDAY|Ramzan Id
2010-09-11|HOLIDAY|Ganesh Chaturthi
2010-10-02|HOLIDAY|Gandhi Jayanti
2010-10-17|HOLIDAY|Dasara
2010-11-05|HOLIDAY|Laxmi Puja; Muhurat session separately verified
2010-11-07|HOLIDAY|Bhau Bhij
2010-11-17|HOLIDAY|Bakri Id
2010-11-21|HOLIDAY|Gurunanak Jayanti
2010-12-17|HOLIDAY|Moharram
2010-12-25|HOLIDAY|Christmas
""",
    "NSE_CMTR_16062_2010_SPECIAL_SESSION": """
2010-11-05|SPECIAL_SESSION|Muhurat Trading - Diwali
""",
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
    raw = REVIEW_ROWS[source_id]
    rows: list[dict[str, str]] = []
    for line in raw.splitlines():
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
            "PRODUCTION_INFLUENCE=false",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_sources(recovery_root: Path, output_root: Path) -> tuple[Path, ...]:
    attempts_path = recovery_root / "source_candidate_attempts.json"
    attempts = json.loads(attempts_path.read_text(encoding="utf-8"))
    if not isinstance(attempts, list):
        raise RuntimeError("RECOVERY_ATTEMPTS_INVALID")
    by_source = {str(item["source_id"]): item for item in attempts}
    if set(by_source) != set(REVIEW_ROWS):
        missing = sorted(set(REVIEW_ROWS) - set(by_source))
        extra = sorted(set(by_source) - set(REVIEW_ROWS))
        raise RuntimeError(f"REVIEW_SOURCE_SET_MISMATCH missing={missing} extra={extra}")

    output_root.mkdir(parents=True, exist_ok=True)
    master_rows: list[dict[str, str]] = []
    manifest_rows: list[dict[str, object]] = []
    source_paths: list[Path] = []

    for source_id in sorted(REVIEW_ROWS):
        attempt = by_source[source_id]
        if attempt.get("recovery_state") != "VERIFIED_OFFICIAL_EVIDENCE":
            raise RuntimeError(f"SOURCE_NOT_VERIFIED:{source_id}")
        if attempt.get("content_validation_passed") is not True:
            raise RuntimeError(f"SOURCE_CONTENT_INVALID:{source_id}")

        rows = _parsed_rows(source_id)
        master_rows.extend(rows)
        review_path = output_root / "reviews" / f"{source_id}.csv"
        validation_path = output_root / "validation" / f"{source_id}.txt"
        _write_csv(review_path, rows)
        _write_validation(validation_path, attempt)

        document_path = Path(str(attempt["document_path"]))
        extracted_text_path = Path(str(attempt["extracted_text_path"]))
        year = int(attempt["year"])
        source_path = output_root / "sources" / f"nse_{year}_{source_id}.json"
        build_reviewed_official_calendar_source(
            review_csv=review_path,
            source_document=document_path,
            source_url=str(attempt["final_url"]),
            source_id=source_id,
            covered_years=(year,),
            output=source_path,
            segment_scope="CAPITAL_MARKET",
            extracted_text=extracted_text_path,
            content_validation=validation_path,
        )
        payload = validate_hash_bound_official_calendar_source(
            source_path,
            require_capital_market_scope=True,
        )
        holidays = payload.get("holidays")
        special_sessions = payload.get("special_sessions")
        if not isinstance(holidays, list):
            raise RuntimeError(f"SOURCE_HOLIDAYS_INVALID:{source_id}")
        if not isinstance(special_sessions, list):
            raise RuntimeError(f"SOURCE_SPECIAL_SESSIONS_INVALID:{source_id}")
        source_paths.append(source_path)
        manifest_rows.append(
            {
                "year": year,
                "source_id": source_id,
                "source_path": str(source_path),
                "source_json_sha256": _sha256(source_path),
                "source_document_sha256": payload["source_document_sha256"],
                "review_csv_sha256": payload["review_csv_sha256"],
                "holiday_count": len(holidays),
                "special_session_count": len(special_sessions),
                "segment_scope": payload["segment_scope"],
            }
        )

    master_rows.sort(key=lambda row: (row["trading_date"], row["source_id"]))
    _write_csv(output_root / "reviewed_calendar_master.csv", tuple(master_rows))
    manifest = {
        "covered_years": [2005, 2006, 2007, 2008, 2009, 2010],
        "source_count": len(manifest_rows),
        "holiday_row_count": sum(
            row["classification"] == "HOLIDAY" for row in master_rows
        ),
        "special_session_row_count": sum(
            row["classification"] == "SPECIAL_SESSION" for row in master_rows
        ),
        "sources": manifest_rows,
        "manual_review_completed": True,
        "classification_inferred_from_archive_status": False,
        "classification_inferred_from_observed_candles": False,
        "calendar_certification_permitted": False,
        "production_influence": False,
    }
    manifest_path = output_root / "reviewed_source_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    hashes = [
        f"{_sha256(path)}  {path}"
        for path in sorted(output_root.rglob("*"))
        if path.is_file() and path.name != "evidence_hashes.txt"
    ]
    (output_root / "evidence_hashes.txt").write_text(
        "\n".join(hashes) + "\n",
        encoding="utf-8",
    )
    return tuple(source_paths)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recovery-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    source_paths = build_sources(args.recovery_root, args.output_root)
    print("===== DSI-010 REVIEWED PRE-2011 CALENDAR SOURCES =====")
    print(f"Reviewed Sources: {len(source_paths)}")
    print("Covered Years: 2005,2006,2007,2008,2009,2010")
    print(f"Source Paths: {len(source_paths)}")
    print("MANUAL_REVIEW_COMPLETED=true")
    print("CALENDAR_CERTIFICATION_PERMITTED=false")
    print("PRODUCTION_INFLUENCE=false")


if __name__ == "__main__":
    main()
