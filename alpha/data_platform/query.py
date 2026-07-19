from __future__ import annotations

from datetime import UTC, datetime

from alpha.data_platform.dataset_registry import DatasetRegistry
from alpha.data_platform.models import (
    CanonicalObservation,
    DataQuery,
    DatasetCategory,
    QueryPlan,
    QueryResult,
    QuerySubject,
    stable_hash,
)

_SUBJECT_CATEGORIES: dict[QuerySubject, tuple[DatasetCategory, ...]] = {
    QuerySubject.OHLCV: (DatasetCategory.DAILY_OHLCV,),
    QuerySubject.DELIVERY: (DatasetCategory.DELIVERY,),
    QuerySubject.CORPORATE_ACTIONS: (DatasetCategory.CORPORATE_ACTION,),
    QuerySubject.SECURITY_MASTER: (
        DatasetCategory.SECURITY_MASTER,
        DatasetCategory.IDENTITY,
        DatasetCategory.SYMBOL_HISTORY,
    ),
    QuerySubject.INDEX_MEMBERSHIP: (DatasetCategory.INDEX_MEMBERSHIP,),
    QuerySubject.INDEX_OHLCV: (DatasetCategory.INDEX_OHLCV,),
    QuerySubject.TRADING_CALENDAR: (DatasetCategory.TRADING_CALENDAR,),
}


class CanonicalQueryEngine:
    """Query canonical observations without invoking replay or source acquisition."""

    def __init__(
        self,
        registry: DatasetRegistry,
        observations: tuple[CanonicalObservation, ...] = (),
        *,
        warehouse_version: str = "WAREHOUSE_V2_CANONICAL_DRAFT",
    ) -> None:
        self._registry = registry
        self._observations = tuple(
            sorted(
                observations,
                key=lambda item: (
                    item.dataset_id,
                    item.observed_on,
                    item.observation_key,
                    item.known_at,
                ),
            )
        )
        self._warehouse_version = warehouse_version

    def compile(self, query: DataQuery) -> QueryPlan:
        dataset = self._registry.get(query.dataset_id)
        if dataset.category not in _SUBJECT_CATEGORIES[query.subject]:
            raise ValueError(
                f"ADP subject {query.subject.value} is incompatible with "
                f"{dataset.category.value}"
            )
        filters = (
            ("market_start", _text(query.market_start)),
            ("market_end", _text(query.market_end)),
            ("knowledge_as_of", _text(query.knowledge_as_of)),
            ("symbols", "|".join(query.symbols)),
            ("security_ids", "|".join(query.security_ids)),
            ("index_ids", "|".join(query.index_ids)),
            ("limit", str(query.limit)),
        )
        payload = (query.dataset_id, query.subject.value, filters, dataset.version)
        return QueryPlan(
            query_id="adp-query-" + stable_hash(payload)[:24],
            dataset_id=query.dataset_id,
            subject=query.subject,
            filters=filters,
            point_in_time_enforced=True,
            warehouse_version=self._warehouse_version,
            dataset_version=dataset.version,
        )

    def execute(self, query: DataQuery) -> QueryResult:
        plan = self.compile(query)
        rows = tuple(
            item
            for item in self._observations
            if item.dataset_id == query.dataset_id and _matches(item, query)
        )[: query.limit]
        dataset = self._registry.get(query.dataset_id)
        status = (
            "MATCHED"
            if rows
            else "DATASET_NOT_ACQUIRED"
            if not dataset.acquired
            else "NO_MATCHING_RECORDS"
        )
        return QueryResult(plan=plan, records=rows, status=status)


def subject_for_category(category: DatasetCategory) -> QuerySubject:
    for subject, categories in _SUBJECT_CATEGORIES.items():
        if category in categories:
            return subject
    raise ValueError(f"ADP category has no query subject: {category.value}")


def _matches(item: CanonicalObservation, query: DataQuery) -> bool:
    state_subject = query.subject in {
        QuerySubject.SECURITY_MASTER,
        QuerySubject.INDEX_MEMBERSHIP,
    }
    if not state_subject:
        if query.market_start and item.observed_on < query.market_start:
            return False
        if query.market_end and item.observed_on > query.market_end:
            return False
    if query.knowledge_as_of and item.known_at > query.knowledge_as_of:
        return False
    market_date = query.market_end or query.market_start
    if market_date is not None:
        if item.effective_from > market_date:
            return False
        if item.effective_to is not None and item.effective_to < market_date:
            return False
    if query.symbols and _symbol(item) not in query.symbols:
        return False
    if query.security_ids and _security_id(item) not in query.security_ids:
        return False
    if query.index_ids and _index_id(item) not in query.index_ids:
        return False
    return True


def _symbol(item: CanonicalObservation) -> str:
    value = item.fields.get("symbol") or item.fields.get("symbol_as_traded")
    return "" if value is None else str(value).upper()


def _security_id(item: CanonicalObservation) -> str:
    value = item.fields.get("security_id")
    return "" if value is None else str(value)


def _index_id(item: CanonicalObservation) -> str:
    value = item.fields.get("index_id")
    return "" if value is None else str(value).upper()


def _text(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return normalized.astimezone(UTC).isoformat()
    return str(value)


__all__ = ["CanonicalQueryEngine", "subject_for_category"]
