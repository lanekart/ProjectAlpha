"""Discover source schemas for canonical historical-truth recovery."""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FieldProfile:
    """Observed characteristics for one source field."""

    name: str
    inferred_type: str
    nullable: bool
    unique_count: int
    non_null_count: int
    candidate_key: bool
    sample_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceSchema:
    """Machine-readable schema inferred from one source file."""

    source_name: str
    source_path: str
    source_format: str
    row_count: int
    fields: tuple[FieldProfile, ...]
    candidate_primary_keys: tuple[str, ...]
    candidate_date_fields: tuple[str, ...]
    candidate_lineage_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MappingCandidate:
    """Candidate mapping from a raw field into a canonical field."""

    source_name: str
    raw_field: str
    canonical_field: str
    confidence: float
    rationale: str


@dataclass(frozen=True, slots=True)
class SchemaDiscoveryResult:
    """Complete deterministic schema discovery output."""

    sources: tuple[SourceSchema, ...]
    mappings: tuple[MappingCandidate, ...]
    relationship_candidates: tuple[tuple[str, str, str], ...]


_CANONICAL_ALIASES: Mapping[str, tuple[str, ...]] = {
    "security_id": (
        "security_id",
        "instrument_id",
        "security_code",
        "scrip_code",
    ),
    "isin": ("isin", "isin_code"),
    "symbol": ("symbol", "ticker", "trading_symbol", "tradingsymbol"),
    "listing_date": ("listing_date", "official_listing_date", "listed_on"),
    "delisting_date": (
        "delisting_date",
        "official_delisting_date",
        "delisted_on",
    ),
    "effective_from": (
        "effective_from",
        "valid_from",
        "start_date",
        "from_date",
    ),
    "effective_to": ("effective_to", "valid_to", "end_date", "to_date"),
    "sector": ("sector", "sector_name"),
    "industry": ("industry", "industry_name"),
    "index_name": ("index", "index_name", "benchmark"),
}

_DATE_TOKENS = ("date", "from", "to", "effective", "listed", "delisted")
_LINEAGE_TOKENS = (
    "predecessor",
    "successor",
    "previous",
    "historical",
    "renamed",
    "symbol_change",
    "lineage",
)


def discover_sources(paths: Sequence[Path]) -> SchemaDiscoveryResult:
    """Inspect supported source files and infer schemas and relationships."""

    schemas = tuple(
        sorted((_inspect_source(path) for path in paths), key=_schema_key)
    )
    mappings = tuple(
        sorted(
            (
                candidate
                for schema in schemas
                for field in schema.fields
                for candidate in _mapping_candidates(schema.source_name, field.name)
            ),
            key=_mapping_key,
        )
    )
    relationships = _relationship_candidates(schemas)
    return SchemaDiscoveryResult(
        sources=schemas,
        mappings=mappings,
        relationship_candidates=relationships,
    )


def export_schema_discovery(
    result: SchemaDiscoveryResult,
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic JSON artifacts and a compact Markdown report."""

    output.mkdir(parents=True, exist_ok=True)
    source_paths: list[Path] = []
    for schema in result.sources:
        path = output / f"{schema.source_name}.schema.json"
        path.write_text(
            json.dumps(asdict(schema), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        source_paths.append(path)

    mappings_path = output / "canonical_mapping_candidates.json"
    mappings_path.write_text(
        json.dumps(
            [asdict(item) for item in result.mappings],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    relationships_path = output / "relationship_graph.json"
    relationships_path.write_text(
        json.dumps(result.relationship_candidates, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report_path = output / "report.md"
    report_path.write_text(_render_report(result), encoding="utf-8")
    return (*source_paths, mappings_path, relationships_path, report_path)


def _inspect_source(path: Path) -> SourceSchema:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = _read_csv(path)
        source_format = "csv"
    elif suffix in {".json", ".jsonl"}:
        rows = _read_json(path)
        source_format = suffix.removeprefix(".")
    else:
        raise ValueError(f"unsupported schema source: {path}")

    fields = _profile_fields(rows)
    return SourceSchema(
        source_name=path.stem,
        source_path=str(path),
        source_format=source_format,
        row_count=len(rows),
        fields=fields,
        candidate_primary_keys=tuple(
            field.name for field in fields if field.candidate_key
        ),
        candidate_date_fields=tuple(
            field.name
            for field in fields
            if _contains_token(field.name, _DATE_TOKENS)
        ),
        candidate_lineage_fields=tuple(
            field.name
            for field in fields
            if _contains_token(field.name, _LINEAGE_TOKENS)
        ),
    )


def _read_csv(path: Path) -> tuple[Mapping[str, object], ...]:
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _read_json(path: Path) -> tuple[Mapping[str, object], ...]:
    payload: object
    if path.suffix.lower() == ".jsonl":
        payload = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(payload, Mapping):
        nested_records = next(
            (
                value
                for value in payload.values()
                if isinstance(value, list)
                and all(isinstance(item, Mapping) for item in value)
            ),
            None,
        )
        payload = nested_records if nested_records is not None else [payload]

    if not isinstance(payload, list):
        raise ValueError(f"JSON source must contain records: {path}")
    if not all(isinstance(item, Mapping) for item in payload):
        raise ValueError(f"JSON source must contain records: {path}")

    records: list[Mapping[str, object]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            raise ValueError(f"JSON source must contain records: {path}")
        records.append(dict(item))
    return tuple(records)


def _profile_fields(
    rows: Sequence[Mapping[str, object]],
) -> tuple[FieldProfile, ...]:
    names = sorted({str(key) for row in rows for key in row})
    profiles: list[FieldProfile] = []
    for name in names:
        values = tuple(row.get(name) for row in rows)
        non_null = tuple(value for value in values if not _is_null(value))
        rendered = tuple(_render_value(value) for value in non_null)
        unique = len(set(rendered))
        profiles.append(
            FieldProfile(
                name=name,
                inferred_type=_infer_type(non_null),
                nullable=len(non_null) != len(rows),
                unique_count=unique,
                non_null_count=len(non_null),
                candidate_key=(
                    bool(rows)
                    and len(non_null) == len(rows)
                    and unique == len(rows)
                ),
                sample_values=tuple(sorted(set(rendered))[:3]),
            )
        )
    return tuple(profiles)


def _infer_type(values: Iterable[object]) -> str:
    kinds = Counter(_value_kind(value) for value in values)
    if not kinds:
        return "unknown"
    if len(kinds) == 1:
        return next(iter(kinds))
    numeric = set(kinds) <= {"integer", "number"}
    return "number" if numeric else "mixed"


def _value_kind(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return "string"
        if _looks_like_integer(stripped):
            return "integer"
        if _looks_like_number(stripped):
            return "number"
        if _looks_like_date(stripped):
            return "date"
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def _mapping_candidates(
    source_name: str,
    raw_field: str,
) -> tuple[MappingCandidate, ...]:
    normalized = _normalize(raw_field)
    candidates: list[MappingCandidate] = []
    for canonical, aliases in _CANONICAL_ALIASES.items():
        normalized_aliases = tuple(_normalize(alias) for alias in aliases)
        if normalized == _normalize(canonical):
            confidence = 1.0
            rationale = "Exact canonical field match."
        elif normalized in normalized_aliases:
            confidence = 0.95
            rationale = "Known semantic alias."
        else:
            continue
        candidates.append(
            MappingCandidate(
                source_name=source_name,
                raw_field=raw_field,
                canonical_field=canonical,
                confidence=confidence,
                rationale=rationale,
            )
        )
    return tuple(candidates)


def _relationship_candidates(
    schemas: Sequence[SourceSchema],
) -> tuple[tuple[str, str, str], ...]:
    by_field: dict[str, list[str]] = {}
    for schema in schemas:
        for field_profile in schema.fields:
            normalized_field = _normalize(field_profile.name)
            by_field.setdefault(normalized_field, []).append(schema.source_name)

    relationships: set[tuple[str, str, str]] = set()
    for field_name, sources in by_field.items():
        if len(sources) < 2:
            continue
        ordered = sorted(set(sources))
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                relationships.add((left, right, field_name))
    return tuple(sorted(relationships))


def _render_report(result: SchemaDiscoveryResult) -> str:
    lines = ["# Entity Schema Discovery", ""]
    for schema in result.sources:
        lines.extend(
            [
                f"## {schema.source_name}",
                "",
                f"- Format: `{schema.source_format}`",
                f"- Rows: `{schema.row_count}`",
                f"- Fields: `{len(schema.fields)}`",
                (
                    "- Candidate keys: `"
                    f"{', '.join(schema.candidate_primary_keys) or 'NONE'}`"
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Mapping Candidates",
            "",
            f"- Count: `{len(result.mappings)}`",
            "",
            "## Relationship Candidates",
            "",
            f"- Count: `{len(result.relationship_candidates)}`",
            "",
        ]
    )
    return "\n".join(lines)


def _is_null(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _render_value(value: object) -> str:
    if isinstance(value, (Mapping, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _looks_like_integer(value: str) -> bool:
    return value.lstrip("+-").isdigit()


def _looks_like_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _looks_like_date(value: str) -> bool:
    if len(value) < 8:
        return False
    separators = value.count("-") + value.count("/")
    return separators >= 2 and any(char.isdigit() for char in value)


def _contains_token(value: str, tokens: tuple[str, ...]) -> bool:
    normalized = _normalize(value)
    return any(token in normalized for token in tokens)


def _normalize(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    return "_".join(part for part in normalized.split("_") if part)


def _schema_key(schema: SourceSchema) -> tuple[str, str]:
    return schema.source_name, schema.source_path


def _mapping_key(candidate: MappingCandidate) -> tuple[str, str, str]:
    return candidate.source_name, candidate.raw_field, candidate.canonical_field
