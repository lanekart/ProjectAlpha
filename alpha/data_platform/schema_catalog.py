from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal

from alpha.data_platform.models import (
    DatasetSchema,
    FieldType,
    PlatformLayer,
    Scalar,
    SchemaField,
    SchemaValidationResult,
    TruthClass,
    stable_hash,
)


class SchemaCatalog:
    def __init__(self, schemas: tuple[DatasetSchema, ...]) -> None:
        ordered = tuple(sorted(schemas, key=lambda item: item.schema_version))
        if len({item.schema_version for item in ordered}) != len(ordered):
            raise ValueError("ADP schema versions must be unique")
        self._schemas = ordered

    @property
    def schemas(self) -> tuple[DatasetSchema, ...]:
        return self._schemas

    @property
    def catalog_hash(self) -> str:
        return stable_hash(self._schemas)

    def get(self, schema_version: str) -> DatasetSchema:
        for schema in self._schemas:
            if schema.schema_version == schema_version:
                return schema
        raise KeyError(f"ADP schema is not registered: {schema_version}")

    def validate(
        self,
        schema_version: str,
        payload: Mapping[str, Scalar],
    ) -> SchemaValidationResult:
        schema = self.get(schema_version)
        expected = {item.name: item for item in schema.fields}
        actual = set(payload)
        missing = tuple(
            sorted(
                name
                for name, field in expected.items()
                if not field.nullable
                and (name not in actual or payload.get(name) is None)
            )
        )
        unexpected = tuple(sorted(actual - set(expected)))
        invalid = tuple(
            sorted(
                name
                for name, value in payload.items()
                if name in expected
                and value is not None
                and not _valid_type(value, expected[name].field_type)
            )
        )
        return SchemaValidationResult(
            schema_version=schema_version,
            valid=not missing and not unexpected and not invalid,
            missing_fields=missing,
            unexpected_fields=unexpected,
            invalid_types=invalid,
        )


def default_schema_catalog() -> SchemaCatalog:
    return SchemaCatalog(
        (
            _schema(
                "adp-daily-ohlcv-v1",
                "Canonical Daily OHLCV",
                ("exchange", "trading_date", "security_id"),
                (
                    _field("exchange", FieldType.TEXT),
                    _field("trading_date", FieldType.DATE),
                    _field("security_id", FieldType.TEXT),
                    _field("symbol_as_traded", FieldType.TEXT),
                    _field("series", FieldType.TEXT, nullable=True),
                    _field("isin", FieldType.TEXT, nullable=True),
                    _field("open", FieldType.DECIMAL),
                    _field("high", FieldType.DECIMAL),
                    _field("low", FieldType.DECIMAL),
                    _field("close", FieldType.DECIMAL),
                    _field("volume", FieldType.DECIMAL),
                    _field("turnover", FieldType.DECIMAL, nullable=True),
                ),
            ),
            _schema(
                "adp-delivery-v1",
                "Canonical Delivery Statistics",
                ("exchange", "trading_date", "security_id"),
                (
                    _field("exchange", FieldType.TEXT),
                    _field("trading_date", FieldType.DATE),
                    _field("security_id", FieldType.TEXT),
                    _field("symbol", FieldType.TEXT),
                    _field("deliverable_quantity", FieldType.DECIMAL, nullable=True),
                    _field("deliverable_percentage", FieldType.DECIMAL, nullable=True),
                ),
            ),
            _schema(
                "adp-corporate-action-v1",
                "Canonical Corporate Action",
                ("corporate_action_id",),
                (
                    _field("corporate_action_id", FieldType.TEXT),
                    _field("security_id", FieldType.TEXT),
                    _field("exchange", FieldType.TEXT),
                    _field("action_type", FieldType.TEXT),
                    _field("announcement_date", FieldType.DATE),
                    _field("effective_date", FieldType.DATE, nullable=True),
                    _field("ratio", FieldType.TEXT, nullable=True),
                    _field("cash_amount", FieldType.DECIMAL, nullable=True),
                    _field("old_symbol", FieldType.TEXT, nullable=True),
                    _field("new_symbol", FieldType.TEXT, nullable=True),
                    _field("old_isin", FieldType.TEXT, nullable=True),
                    _field("new_isin", FieldType.TEXT, nullable=True),
                ),
            ),
            _schema(
                "adp-security-master-v1",
                "Canonical Security Master",
                ("security_id", "valid_from"),
                (
                    _field("security_id", FieldType.TEXT),
                    _field("exchange", FieldType.TEXT),
                    _field("symbol", FieldType.TEXT),
                    _field("series", FieldType.TEXT, nullable=True),
                    _field("isin", FieldType.TEXT, nullable=True),
                    _field("company_name", FieldType.TEXT, nullable=True),
                    _field("listing_date", FieldType.DATE, nullable=True),
                    _field("delisting_date", FieldType.DATE, nullable=True),
                    _field("valid_from", FieldType.DATE),
                    _field("valid_to", FieldType.DATE, nullable=True),
                ),
            ),
            _schema(
                "adp-isin-map-v1",
                "Canonical ISIN Mapping",
                ("security_id", "valid_from"),
                (
                    _field("security_id", FieldType.TEXT),
                    _field("isin", FieldType.TEXT),
                    _field("valid_from", FieldType.DATE),
                    _field("valid_to", FieldType.DATE, nullable=True),
                ),
            ),
            _schema(
                "adp-symbol-history-v1",
                "Canonical Symbol History",
                ("security_id", "valid_from"),
                (
                    _field("security_id", FieldType.TEXT),
                    _field("symbol", FieldType.TEXT),
                    _field("name", FieldType.TEXT, nullable=True),
                    _field("valid_from", FieldType.DATE),
                    _field("valid_to", FieldType.DATE, nullable=True),
                ),
            ),
            _schema(
                "adp-trading-calendar-v1",
                "Canonical Trading Calendar",
                ("exchange", "session_date"),
                (
                    _field("exchange", FieldType.TEXT),
                    _field("session_date", FieldType.DATE),
                    _field("is_session", FieldType.BOOLEAN),
                    _field("session_type", FieldType.TEXT),
                ),
            ),
            _schema(
                "adp-index-ohlcv-v1",
                "Canonical Index OHLCV",
                ("index_id", "trading_date"),
                (
                    _field("index_id", FieldType.TEXT),
                    _field("index_name", FieldType.TEXT),
                    _field("trading_date", FieldType.DATE),
                    _field("open", FieldType.DECIMAL, nullable=True),
                    _field("high", FieldType.DECIMAL, nullable=True),
                    _field("low", FieldType.DECIMAL, nullable=True),
                    _field("close", FieldType.DECIMAL),
                    _field("volume", FieldType.DECIMAL, nullable=True),
                ),
            ),
            _schema(
                "adp-index-membership-v1",
                "Canonical Historical Index Membership",
                ("index_id", "effective_date", "security_id"),
                (
                    _field("index_id", FieldType.TEXT),
                    _field("effective_date", FieldType.DATE),
                    _field("security_id", FieldType.TEXT),
                    _field("symbol_as_of", FieldType.TEXT),
                    _field("added", FieldType.BOOLEAN),
                    _field("removed", FieldType.BOOLEAN),
                    _field("complete_snapshot", FieldType.BOOLEAN),
                ),
            ),
        )
    )


def _schema(
    version: str,
    name: str,
    primary_key: tuple[str, ...],
    fields: tuple[SchemaField, ...],
) -> DatasetSchema:
    return DatasetSchema(
        schema_version=version,
        name=name,
        layer=PlatformLayer.HISTORICAL_TRUTH,
        primary_key=primary_key,
        fields=fields,
    )


def _field(
    name: str,
    field_type: FieldType,
    *,
    nullable: bool = False,
) -> SchemaField:
    return SchemaField(
        name=name,
        field_type=field_type,
        nullable=nullable,
        truth_class=TruthClass.UNKNOWN,
        description=f"Canonical {name.replace('_', ' ')} field.",
    )


def _valid_type(value: Scalar, expected: FieldType) -> bool:
    if expected is FieldType.TEXT:
        return isinstance(value, str)
    if expected is FieldType.DATE:
        return isinstance(value, date) and not isinstance(value, datetime)
    if expected is FieldType.DATETIME:
        return isinstance(value, datetime)
    if expected is FieldType.DECIMAL:
        return isinstance(value, Decimal)
    if expected is FieldType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, bool)


__all__ = ["SchemaCatalog", "default_schema_catalog"]
