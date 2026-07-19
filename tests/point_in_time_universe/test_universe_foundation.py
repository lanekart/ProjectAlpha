from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from alpha.application.point_in_time_universe_cli import universe_app
from alpha.point_in_time_universe.corporate_actions import CorporateActionHistory
from alpha.point_in_time_universe.exports import UniverseExporter
from alpha.point_in_time_universe.index_membership import IndexMembershipHistory
from alpha.point_in_time_universe.integrity import UniverseIntegrityEngine
from alpha.point_in_time_universe.listing_history import ListingHistory
from alpha.point_in_time_universe.models import (
    SCHEMA_VERSION,
    ConfidenceGrade,
    CorporateActionRecord,
    CorporateActionType,
    EffectiveInterval,
    EvidenceStatus,
    HistoricalSymbol,
    IndexEvidenceWindow,
    IndexMembershipRecord,
    ListingHistoryRecord,
    SectorMembershipRecord,
    SecurityIdentity,
    SurvivorshipStatus,
    TradabilityStatus,
    UniverseCoverage,
    UniverseManifest,
    UniverseMember,
    UniverseObservation,
    UniverseSnapshot,
)
from alpha.point_in_time_universe.sector_history import SectorHistory
from alpha.point_in_time_universe.security_master import SecurityMaster
from alpha.point_in_time_universe.survivorship_audit import SurvivorshipAuditEngine
from alpha.point_in_time_universe.universe_builder import (
    LegacyPointInTimeUniverseMaterializer,
    PointInTimeUniverseBuilder,
)

JAN_1 = date(2020, 1, 1)
JAN_10 = date(2020, 1, 10)
JAN_20 = date(2020, 1, 20)
JAN_31 = date(2020, 1, 31)
FEB_1 = date(2020, 2, 1)
FEB_15 = date(2020, 2, 15)
FEB_16 = date(2020, 2, 16)
FEB_28 = date(2020, 2, 28)
MAR_1 = date(2020, 3, 1)
MAR_31 = date(2020, 3, 31)
APR_1 = date(2020, 4, 1)
DEC_31 = date(2020, 12, 31)


def test_ipo_inclusion_and_delisting_exclusion() -> None:
    builder = _builder()

    before = builder.build(JAN_1, observations=(_observation(JAN_1, "OLD"),))
    first = builder.build(JAN_10, observations=(_observation(JAN_10, "OLD"),))
    after = builder.build(APR_1, observations=(_observation(APR_1, "NEW"),))

    assert before.members == ()
    assert len(first.members) == 1
    assert first.members[0].tradability is TradabilityStatus.TRADABLE
    assert after.members == ()


def test_symbol_change_uses_effective_interval() -> None:
    master = _master()

    assert master.resolve_symbol("OLD", JAN_31) is not None
    assert master.resolve_symbol("NEW", FEB_1) is not None
    assert master.resolve_symbol("NEW", JAN_31) is None
    snapshot = _builder().build(FEB_1, observations=(_observation(FEB_1, "NEW"),))
    assert snapshot.members[0].symbol == "NEW"


def test_index_membership_is_effective_dated() -> None:
    history = _indices()

    added = history.snapshot("NIFTY50", JAN_10, previous_date=JAN_1)
    removed = history.snapshot("NIFTY50", MAR_1, previous_date=FEB_28)

    assert added.status is EvidenceStatus.KNOWN
    assert added.members == ("SEC-1",)
    assert added.additions == ("SEC-1",)
    assert removed.members == ()
    assert removed.removals == ("SEC-1",)


def test_sector_history_does_not_backfill_future_classification() -> None:
    sectors = _sectors()

    old, old_status = sectors.classification("SEC-1", FEB_15)
    new, new_status = sectors.classification("SEC-1", FEB_16)
    unknown, unknown_status = sectors.classification("SEC-1", JAN_1)

    assert old is not None and old.sector == "TECHNOLOGY"
    assert new is not None and new.sector == "CONSUMER"
    assert old_status is new_status is EvidenceStatus.KNOWN
    assert unknown is None and unknown_status is EvidenceStatus.UNKNOWN


def test_split_and_merger_preserve_lineage() -> None:
    actions = _actions()

    split = actions.actions_for("SEC-1", through=FEB_1)[0]

    assert split.action_type is CorporateActionType.SPLIT
    assert split.ratio_numerator == Decimal("2")
    assert actions.lineage("SEC-1") == ("SEC-1", "SEC-2")


def test_corporate_action_lineage_rejects_cycles() -> None:
    first = _action(
        "MERGE-1",
        CorporateActionType.MERGER,
        predecessor_security_ids=("SEC-1",),
        successor_security_ids=("SEC-2",),
    )
    second = _action(
        "MERGE-2",
        CorporateActionType.MERGER,
        predecessor_security_ids=("SEC-2",),
        successor_security_ids=("SEC-1",),
    )

    with pytest.raises(ValueError, match="cycle"):
        CorporateActionHistory((first, second))


def test_unknown_history_remains_unknown() -> None:
    builder = PointInTimeUniverseBuilder(
        security_master=_master(),
        listings=_listings(),
        indices=IndexMembershipHistory(),
        sectors=SectorHistory(),
        corporate_actions=CorporateActionHistory(),
    )

    snapshot = builder.build(JAN_10, observations=(_observation(JAN_10, "OLD"),))

    assert all(value is None for _, value in snapshot.members[0].index_memberships)
    assert snapshot.members[0].sector_status is EvidenceStatus.UNKNOWN
    assert "NIFTY50" in snapshot.unknown_dimensions
    assert "SECTOR" in snapshot.unknown_dimensions
    assert snapshot.confidence is ConfidenceGrade.LOW


def test_survivorship_audit_detects_future_security_leakage() -> None:
    invalid_member = UniverseMember(
        as_of=JAN_1,
        security_id="SEC-1",
        symbol="OLD",
        exchange="NSE",
        tradability=TradabilityStatus.TRADABLE,
        index_memberships=tuple((index, None) for index in _index_names()),
        sector=None,
        sector_status=EvidenceStatus.UNKNOWN,
        listing_valid=False,
        corporate_action_status=EvidenceStatus.UNKNOWN,
        confidence=ConfidenceGrade.LOW,
        evidence=("test",),
    )
    snapshot = UniverseSnapshot(
        as_of=JAN_1,
        members=(invalid_member,),
        index_snapshots=IndexMembershipHistory().all_snapshots(JAN_1),
        confidence=ConfidenceGrade.LOW,
        unknown_dimensions=("SECTOR", "CORPORATE_ACTIONS"),
    )

    result = SurvivorshipAuditEngine().audit(snapshot, security_master=_master())

    assert result.status is SurvivorshipStatus.FAIL
    assert result.future_constituent_leaks == 1


def test_integrity_passes_valid_history_without_promoting_unknowns() -> None:
    snapshot = _builder().build(JAN_10, observations=(_observation(JAN_10, "OLD"),))

    result = UniverseIntegrityEngine().validate(
        security_master=_master_with_successor(),
        listings=_listings(),
        indices=_indices(),
        sectors=_sectors(),
        corporate_actions=_actions(),
        snapshots=(snapshot,),
    )

    assert result.passed is True
    assert result.future_constituent_leaks == 0


def test_exports_are_deterministic(tmp_path: Path) -> None:
    manifest = _manifest()
    exporter = UniverseExporter()
    kwargs = {
        "output_directory": tmp_path,
        "manifest": manifest,
        "security_master": _master().records,
        "universe_size_by_date": (
            {
                "date": JAN_10,
                "observed_universe_size": 1,
                "confidence": ConfidenceGrade.HIGH,
            },
        ),
        "index_membership_changes": (),
        "sector_history": (),
        "listing_history": (),
        "corporate_actions": (),
        "survivorship_audit": (),
        "executive_report": "report\n",
    }
    exporter.export_rows(**kwargs)  # type: ignore[arg-type]
    first = {path.name: path.read_bytes() for path in sorted(tmp_path.iterdir())}
    exporter.export_rows(**kwargs)  # type: ignore[arg-type]
    second = {path.name: path.read_bytes() for path in sorted(tmp_path.iterdir())}

    assert first == second
    assert (
        json.loads((tmp_path / "manifest.json").read_text())["production_influence"]
        is False
    )


def test_legacy_materializer_and_cli_fail_closed(tmp_path: Path) -> None:
    database = tmp_path / "legacy.duckdb"
    output = tmp_path / "universe"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            CREATE TABLE daily_prices (
                symbol VARCHAR, trade_date DATE, open DOUBLE, high DOUBLE,
                low DOUBLE, close DOUBLE, volume DOUBLE, sector VARCHAR,
                exchange VARCHAR
            )
            """
        )
        connection.execute(
            """
            INSERT INTO daily_prices VALUES
            ('AAA', '2020-01-01', 10, 11, 9, 10, 100, 'CURRENT_TECH', 'NSE'),
            ('AAA', '2020-01-02', 10, 11, 9, 10, 100, 'CURRENT_TECH', 'NSE'),
            ('BBB', '2020-01-02', 20, 21, 19, 20, 200, 'CURRENT_BANK', 'NSE')
            """
        )

    result = LegacyPointInTimeUniverseMaterializer().materialize(
        source_database=database, output_directory=output
    )
    runner = CliRunner()
    audit = runner.invoke(universe_app, ["audit", "--output", str(output)])
    on_date = runner.invoke(
        universe_app,
        ["date", "--date", "2020-01-02", "--output", str(output)],
    )
    index = runner.invoke(
        universe_app,
        ["index", "--index", "NIFTY500", "--output", str(output)],
    )

    assert result.manifest.coverage.security_master_size == 2
    assert result.manifest.coverage.unknown_history_percentage == Decimal("100")
    assert audit.exit_code == on_date.exit_code == index.exit_code == 0
    assert "Future Constituent Leaks: 0" in audit.stdout
    assert "Observed Market Instruments: 2" in on_date.stdout
    assert "Equity Eligibility: UNKNOWN" in on_date.stdout
    assert "Known Sessions: 0" in index.stdout
    assert "CURRENT_TECH" not in (output / "sector_history.csv").read_text()


def _identity() -> SecurityIdentity:
    return SecurityIdentity(
        security_id="SEC-1",
        current_symbol="NEW",
        historical_symbols=(
            HistoricalSymbol(
                "OLD",
                EffectiveInterval(JAN_1, JAN_31),
                "official",
                ConfidenceGrade.AUTHORITATIVE,
            ),
            HistoricalSymbol(
                "NEW",
                EffectiveInterval(FEB_1, MAR_31),
                "official",
                ConfidenceGrade.AUTHORITATIVE,
            ),
        ),
        isin="INE000000001",
        listing_date=JAN_10,
        delisting_date=MAR_31,
        exchange="NSE",
        instrument_type="EQUITY",
        active_status="DELISTED",
        corporate_action_lineage=("SPLIT-1", "MERGE-1"),
        source="official",
        confidence=ConfidenceGrade.AUTHORITATIVE,
    )


def _master() -> SecurityMaster:
    return SecurityMaster((_identity(),))


def _master_with_successor() -> SecurityMaster:
    successor = SecurityIdentity(
        security_id="SEC-2",
        current_symbol="SUCCESSOR",
        historical_symbols=(
            HistoricalSymbol(
                "SUCCESSOR",
                EffectiveInterval(MAR_31, DEC_31),
                "official",
                ConfidenceGrade.AUTHORITATIVE,
            ),
        ),
        isin="INE000000002",
        listing_date=MAR_31,
        delisting_date=None,
        exchange="NSE",
        instrument_type="EQUITY",
        active_status="ACTIVE",
        corporate_action_lineage=("MERGE-1",),
        source="official",
        confidence=ConfidenceGrade.AUTHORITATIVE,
    )
    return SecurityMaster((_identity(), successor))


def _listings() -> ListingHistory:
    return ListingHistory(
        (
            ListingHistoryRecord(
                security_id="SEC-1",
                listing_date=JAN_10,
                first_tradable_date=JAN_10,
                delisting_date=MAR_31,
                suspensions=(),
                relisting_dates=(),
                source="official",
                confidence=ConfidenceGrade.AUTHORITATIVE,
            ),
        )
    )


def _indices() -> IndexMembershipHistory:
    return IndexMembershipHistory(
        records=(
            IndexMembershipRecord(
                "SEC-1",
                "NIFTY50",
                EffectiveInterval(JAN_10, FEB_28),
                "official",
                ConfidenceGrade.AUTHORITATIVE,
            ),
        ),
        evidence_windows=(
            IndexEvidenceWindow(
                "NIFTY50",
                EffectiveInterval(JAN_1, DEC_31),
                "official",
                ConfidenceGrade.AUTHORITATIVE,
            ),
        ),
    )


def _sectors() -> SectorHistory:
    return SectorHistory(
        (
            SectorMembershipRecord(
                "SEC-1",
                "TECHNOLOGY",
                "SOFTWARE",
                EffectiveInterval(JAN_10, FEB_15),
                "official",
                ConfidenceGrade.AUTHORITATIVE,
            ),
            SectorMembershipRecord(
                "SEC-1",
                "CONSUMER",
                None,
                EffectiveInterval(FEB_16, MAR_31),
                "official",
                ConfidenceGrade.AUTHORITATIVE,
            ),
        )
    )


def _actions() -> CorporateActionHistory:
    split = CorporateActionRecord(
        action_id="SPLIT-1",
        security_id="SEC-1",
        action_type=CorporateActionType.SPLIT,
        effective_date=JAN_20,
        source="official",
        confidence=ConfidenceGrade.AUTHORITATIVE,
        ratio_numerator=Decimal("2"),
        ratio_denominator=Decimal("1"),
    )
    merger = _action(
        "MERGE-1",
        CorporateActionType.MERGER,
        predecessor_security_ids=("SEC-1",),
        successor_security_ids=("SEC-2",),
    )
    return CorporateActionHistory((split, merger), evidence_complete_through=DEC_31)


def _action(
    action_id: str,
    action_type: CorporateActionType,
    *,
    predecessor_security_ids: tuple[str, ...],
    successor_security_ids: tuple[str, ...],
) -> CorporateActionRecord:
    return CorporateActionRecord(
        action_id=action_id,
        security_id=predecessor_security_ids[0],
        action_type=action_type,
        effective_date=MAR_31,
        source="official",
        confidence=ConfidenceGrade.AUTHORITATIVE,
        predecessor_security_ids=predecessor_security_ids,
        successor_security_ids=successor_security_ids,
    )


def _builder() -> PointInTimeUniverseBuilder:
    return PointInTimeUniverseBuilder(
        security_master=_master(),
        listings=_listings(),
        indices=_indices(),
        sectors=_sectors(),
        corporate_actions=_actions(),
    )


def _observation(as_of: date, symbol: str) -> UniverseObservation:
    return UniverseObservation(
        as_of=as_of,
        security_id="SEC-1",
        symbol=symbol,
        exchange="NSE",
        source="official daily file",
    )


def _index_names() -> tuple[str, ...]:
    return ("NIFTY50", "NIFTY100", "NIFTY200", "NIFTY500")


def _manifest() -> UniverseManifest:
    return UniverseManifest(
        build_id="build-1",
        dataset_version="test-v1",
        schema_version=SCHEMA_VERSION,
        generated_at=datetime(2020, 12, 31, tzinfo=UTC),
        source_database="fixture",
        source_fingerprint="abc",
        coverage=UniverseCoverage(
            first_session=JAN_1,
            last_session=DEC_31,
            sessions=1,
            security_master_size=1,
            instrument_types_known=1,
            observation_rows=1,
            sessions_with_universe=1,
            index_known_sessions=(("NIFTY50", 1),),
            sector_known_security_intervals=2,
            listing_dates_known=1,
            delisting_dates_known=1,
            corporate_actions_known=2,
            unknown_history_percentage=Decimal("0"),
            survivorship_failures=0,
            confidence=ConfidenceGrade.HIGH,
        ),
    )
