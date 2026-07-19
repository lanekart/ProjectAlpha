from __future__ import annotations

from alpha.data_platform.models import ObservationProvenance, QueryResult
from alpha.data_platform.platform import AlphaDataPlatform


def render_platform_summary(platform: AlphaDataPlatform) -> str:
    manifest = platform.manifest
    return "\n".join(
        (
            "Alpha Data Platform",
            f"Platform Version: {manifest.platform_version}",
            f"Architecture Layers: {len(platform.layers)}",
            f"Registered Official Datasets: {manifest.dataset_count}",
            f"Canonical Schemas: {manifest.schema_count}",
            f"Warehouse Releases: {manifest.warehouse_release_count}",
            "Downloaded Files: 0",
            "Warehouse v1 Migration: NOT PERFORMED",
            "Replay Changes: NONE",
            "PRODUCTION_INFLUENCE=false",
            "",
        )
    )


def render_registry(platform: AlphaDataPlatform) -> str:
    lines = [
        "ADP Dataset Registry",
        f"Registry Hash: {platform.registry.registry_hash}",
        f"Datasets: {len(platform.registry.records)}",
    ]
    for item in platform.registry.records:
        lines.append(
            f"- {item.dataset_id}: {item.dataset_name}; source={item.source}; "
            f"status={item.status.value}; version={item.version}; "
            f"coverage=UNKNOWN"
        )
    lines.extend(("PRODUCTION_INFLUENCE=false", ""))
    return "\n".join(lines)


def render_datasets(platform: AlphaDataPlatform) -> str:
    lines = ["ADP Supported Datasets"]
    for item in platform.registry.records:
        entity = ", ".join(item.entities) if item.entities else "ALL_APPLICABLE"
        lines.append(
            f"- {item.dataset_id}: {item.category.value}; {item.source}; "
            f"entities={entity}; acquired={'YES' if item.acquired else 'NO'}"
        )
    lines.extend(("No historical downloads were performed.", ""))
    return "\n".join(lines)


def render_query_result(result: QueryResult) -> str:
    lines = [
        "ADP Query",
        f"Query ID: {result.plan.query_id}",
        f"Dataset: {result.plan.dataset_id}",
        f"Subject: {result.plan.subject.value}",
        f"Dataset Version: {result.plan.dataset_version}",
        f"Warehouse Version: {result.plan.warehouse_version}",
        f"Point-in-Time Enforced: {result.plan.point_in_time_enforced}",
        f"Status: {result.status}",
        f"Records: {len(result.records)}",
    ]
    if result.status == "DATASET_NOT_ACQUIRED":
        lines.append(
            "Reason: Schema is queryable, but official data is not acquired yet."
        )
    lines.extend(("PRODUCTION_INFLUENCE=false", ""))
    return "\n".join(lines)


def render_provenance_model(
    platform: AlphaDataPlatform,
    provenance: ObservationProvenance | None = None,
) -> str:
    lines = [
        "ADP Provenance",
        "Required: source, transformation chain, warehouse version, confidence,",
        "validation status, field truth, last verified, and SHA-256 checksum.",
        "Every observation field must have exactly one truth classification.",
    ]
    if provenance is None:
        lines.append("Observation Provenance: unavailable; no data was acquired.")
    else:
        lines.extend(
            (
                f"Provenance ID: {provenance.provenance_id}",
                f"Dataset: {provenance.dataset_id}",
                f"Validation: {provenance.validation_status.value}",
                f"Confidence: {provenance.confidence.value}",
            )
        )
    lines.extend(
        (
            f"Registry Hash: {platform.registry.registry_hash}",
            "PRODUCTION_INFLUENCE=false",
            "",
        )
    )
    return "\n".join(lines)


def render_architecture(platform: AlphaDataPlatform) -> str:
    lines = ["ADP Architecture"]
    for index, layer in enumerate(platform.layers):
        connector = " ->" if index < len(platform.layers) - 1 else ""
        lines.append(f"{index}. {layer.layer.value}{connector} {layer.purpose}")
    lines.extend(
        (
            "Downstream consumers remain disconnected until a Warehouse v2 release "
            "is acquired, reconciled, frozen, and separately approved.",
            "PRODUCTION_INFLUENCE=false",
            "",
        )
    )
    return "\n".join(lines)


def render_documents(platform: AlphaDataPlatform) -> dict[str, str]:
    return {
        "platform_architecture.md": _platform_architecture(platform),
        "schema_catalog.md": _schema_catalog(platform),
        "provenance_model.md": _provenance_document(platform),
        "truth_classification.md": _truth_document(),
        "confidence_engine.md": _confidence_document(),
        "reconciliation_framework.md": _reconciliation_document(),
        "download_framework.md": _download_document(),
        "query_model.md": _query_document(platform),
        "warehouse_versioning.md": _versioning_document(platform),
        "time_travel_design.md": _time_travel_document(),
        "implementation_blueprint.md": _implementation_blueprint(),
        "executive_report.md": _executive_report(platform),
    }


def _platform_architecture(platform: AlphaDataPlatform) -> str:
    rows = "\n".join(
        f"| {item.layer.value} | {'Yes' if item.mutable else 'No'} | "
        f"{'Yes' if item.regenerative else 'No'} | {item.purpose} |"
        for item in platform.layers
    )
    return f"""# Alpha Data Platform Architecture

Version: {platform.manifest.platform_version}

Official Sources -> Raw -> Normalized -> Historical Truth -> Canonical Warehouse
-> Replay Cache -> approved downstream consumers.

| Layer | Mutable | Regenerative | Contract |
|---|---|---|---|
{rows}

Raw source bytes are append-only. Normalization is lossless and contains no
business logic. Historical Truth resolves identity, validity, corporate actions,
and conflicts. Canonical Warehouse is a versioned read model. Replay Cache is
disposable and keyed by every upstream version.

Warehouse v1 remains untouched. No consumer is redirected in ADP v1.0.

PRODUCTION_INFLUENCE=false
"""


def _schema_catalog(platform: AlphaDataPlatform) -> str:
    sections = ["# ADP Schema Catalog", ""]
    for schema in platform.schemas.schemas:
        sections.extend(
            (
                f"## {schema.schema_version}",
                "",
                f"Layer: {schema.layer.value}",
                f"Primary key: {', '.join(schema.primary_key)}",
                "",
                "| Field | Type | Nullable | Initial Truth Class |",
                "|---|---|---|---|",
            )
        )
        sections.extend(
            f"| {field.name} | {field.field_type.value} | "
            f"{'Yes' if field.nullable else 'No'} | {field.truth_class.value} |"
            for field in schema.fields
        )
        sections.append("")
    sections.extend(
        (
            "Schema validation rejects missing required fields, unexpected fields, "
            "and incompatible types. UNKNOWN is preserved until source provenance "
            "supports a stronger classification.",
            "",
        )
    )
    return "\n".join(sections)


def _provenance_document(platform: AlphaDataPlatform) -> str:
    return f"""# ADP Provenance Model

Every canonical observation records dataset id, source, observation key,
transformation chain, warehouse version, confidence, validation status,
last-verification timestamp, field-level truth classes, and SHA-256 checksum.

Transformation chains are checksum-linked. A discontinuous chain is rejected.
The provenance engine requires the field-truth key set to exactly match the
observation field set. Truth cannot be silently upgraded.

Registry hash: `{platform.registry.registry_hash}`

PRODUCTION_INFLUENCE=false
"""


def _truth_document() -> str:
    return """# Historical Truth Classification

Every field receives exactly one classification:

- OFFICIAL: directly supplied by an authoritative exchange source.
- OBSERVED: observed in a source without independent authoritative confirmation.
- RECONCILED: agrees across independently controlled sources.
- DERIVED: deterministically computed from classified source fields.
- CURRENT_ONLY: valid only for the current state; historical use is prohibited.
- UNKNOWN: evidence is absent or insufficient.

UNKNOWN values remain UNKNOWN. Current classifications cannot be backfilled into
history. DERIVED never means an analytical indicator inside Historical Truth.
"""


def _confidence_document() -> str:
    return """# ADP Confidence Engine

Confidence is HIGH, MEDIUM, or LOW and is based only on official-source status,
independent reconciliation, completeness, corporate-action completeness,
identity certainty, unresolved conflicts, and unknown fields.

Unresolved conflicts cap confidence at LOW. Unknown fields prevent HIGH.
Non-official evidence cannot receive HIGH. Scores and cap reasons are preserved.
"""


def _reconciliation_document() -> str:
    return """# ADP Reconciliation Framework

The engine compares Legacy, official NSE, and official BSE observations by
dataset and immutable observation key. It reports price, volume, missing-session,
missing-observation, duplicate, corporate-action, and identity conflicts.

Conflicts become immutable review records. The engine performs zero automatic
overwrites and selects no preferred observation. Resolution and publication are
separate, explicitly approved future operations.
"""


def _download_document() -> str:
    return """# ADP Download Framework

ADP v1.0 provides a pure acquisition state machine, not a source downloader.
It supports date-partitioned incremental plans, deterministic job ids, resumable
offsets, checkpoints, bounded retries, parallel batches, SHA-256 verification,
and corruption reset while preserving the corruption count.

No HTTP transport, credentials, source URLs, or downloaded bytes are included.
Historical Truth Acquisition v1.0 will supply authorised connectors separately.
"""


def _query_document(platform: AlphaDataPlatform) -> str:
    return f"""# ADP Query Model

Each of the {len(platform.registry.records)} registered datasets is independently
addressable by dataset id. Query subjects cover OHLCV, delivery, corporate
actions, security master, index membership, index OHLCV, and trading calendars.

Filters include market-date range, knowledge cutoff, symbol, immutable security
id, and index id. Every compiled plan records dataset and warehouse versions and
enforces point-in-time filtering. An unacquired dataset returns
DATASET_NOT_ACQUIRED rather than fabricated data.
"""


def _versioning_document(platform: AlphaDataPlatform) -> str:
    rows = "\n".join(
        f"| {item.warehouse_version} | {item.status.value} | "
        f"{item.parent_version or 'None'} | {'Yes' if item.read_only else 'No'} |"
        for item in platform.warehouse_versions.releases
    )
    return f"""# ADP Warehouse Versioning

| Version | Status | Parent | Read Only |
|---|---|---|---|
{rows}

Every replay binding must record warehouse, feature, policy, decision, and all
dataset versions. Draft or planned warehouse releases cannot bind a replay.
Warehouse v1 remains published and read-only; Warehouse v2 is architecture-only.
"""


def _time_travel_document() -> str:
    return """# ADP Time Travel Design

Time travel has two clocks: the market effective date and the knowledge cutoff.
An observation is visible only when it was effective on the requested market
date and its `known_at` timestamp is no later than the requested knowledge time.

This applies uniformly to OHLCV, identities, symbol lineage, corporate actions,
index membership, and calendars. Missing datasets are returned as UNKNOWN; the
engine never substitutes current constituents or classifications.
"""


def _implementation_blueprint() -> str:
    return """# ADP Implementation Blueprint

## Completed in ADP v1.0

1. Freeze platform, layer, registry, schema, truth, confidence, and version APIs.
2. Register official NSE, BSE, broad-index, sector-index, and membership datasets.
3. Implement raw append-only catalog, provenance, reconciliation, query, time
   travel, acquisition state machine, release lineage, and deterministic exports.

## Historical Truth Acquisition v1.0

1. Confirm licensing and retention rights for each source.
2. Implement one authorised connector at a time behind the download framework.
3. Store original bytes in the immutable raw layer and verify checksums.
4. Normalize without business logic, validate schemas, then reconcile sources.
5. Quarantine conflicts and publish no canonical release until quality approval.

## Canonical Warehouse v2 Publication

1. Complete identity and corporate-action lineage.
2. Pass coverage, session, duplication, and point-in-time audits.
3. Freeze dataset versions and a Warehouse v2 release manifest.
4. Run shadow replay parity before any separately approved consumer migration.
"""


def _executive_report(platform: AlphaDataPlatform) -> str:
    index_count = sum(
        item.category.value.startswith("INDEX") for item in platform.registry.records
    )
    return f"""# Alpha Data Platform v1.0 Executive Report

ADP establishes the permanent architecture for historical truth without
downloading data, migrating Warehouse v1, changing replay, or influencing
production.

- Registered official datasets: {len(platform.registry.records)}
- Historical index datasets: {index_count}
- Canonical schemas: {len(platform.schemas.schemas)}
- Architecture layers: {len(platform.layers)}
- Warehouse releases represented: {len(platform.warehouse_versions.releases)}
- Downloaded files: 0
- Warehouse v1 migrated: No
- Production influence: None

The platform is ready for authorised source acquisition, but Warehouse v2 is not
published and no current Alpha consumer reads from ADP. Coverage dates, source
checksums, and dataset confidence remain UNKNOWN/LOW until actual official data
is lawfully acquired and reconciled.

Freeze designation: `{platform.manifest.platform_version}`

PRODUCTION_INFLUENCE=false
"""


__all__ = [
    "render_architecture",
    "render_datasets",
    "render_documents",
    "render_platform_summary",
    "render_provenance_model",
    "render_query_result",
    "render_registry",
]
