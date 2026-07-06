from decimal import Decimal

import pytest

from alpha.research import (
    ResearchExperimentManifest,
    ResearchExperimentRecord,
    ResearchSession,
    ResearchSessionBuilder,
    ResearchSessionEntry,
)


def make_record(
    *,
    experiment_id: str = "exp_0000",
    objective_metric: str = "score",
    objective_value: Decimal = Decimal("1"),
    rank: int = 1,
) -> ResearchExperimentRecord:
    return ResearchExperimentRecord(
        experiment_id=experiment_id,
        parameters={"lookback": 20},
        objective_metric=objective_metric,
        objective_value=objective_value,
        rank=rank,
    )


def make_manifest(
    run_id: str = "run-1",
    *,
    objective_metric: str = "score",
    objective_value: Decimal = Decimal("1"),
) -> ResearchExperimentManifest:
    return ResearchExperimentManifest(
        run_id=run_id,
        objective_metric=objective_metric,
        records=(
            make_record(
                objective_metric=objective_metric,
                objective_value=objective_value,
            ),
        ),
    )


def test_research_session_entry_normalizes_values() -> None:
    manifest = make_manifest()

    entry = ResearchSessionEntry(
        label=" baseline ",
        manifest=manifest,
        strategy_name=" momentum ",
        notes=" primary candidate ",
        metadata={"owner": "research"},
    )

    assert entry.label == "baseline"
    assert entry.strategy_name == "momentum"
    assert entry.notes == "primary candidate"
    assert entry.run_id == "run-1"
    assert entry.objective_metric == "score"
    assert entry.best_record is manifest.best_record
    assert entry.best_objective_value == Decimal("1")
    assert entry.metadata == {"owner": "research"}


def test_research_session_exposes_summary_and_best_entry() -> None:
    baseline = ResearchSessionEntry(
        label="baseline",
        manifest=make_manifest(run_id="run-1", objective_value=Decimal("1")),
        strategy_name="momentum",
    )
    candidate = ResearchSessionEntry(
        label="candidate",
        manifest=make_manifest(run_id="run-2", objective_value=Decimal("2")),
        strategy_name="momentum",
    )

    session = ResearchSession(
        session_id=" session-1 ",
        name=" Momentum Research ",
        description=" production research ",
        entries=(baseline, candidate),
        metadata={"owner": "quant"},
    )

    summary = session.summary()

    assert session.session_id == "session-1"
    assert session.name == "Momentum Research"
    assert session.description == "production research"
    assert session.entry_count == 2
    assert session.objective_metrics == ("score",)
    assert session.best_entry is candidate
    assert session.best_record is candidate.best_record
    assert summary.session_id == "session-1"
    assert summary.entry_count == 2
    assert summary.best_entry is candidate
    assert summary.metadata == {"owner": "quant"}


def test_research_session_uses_label_as_deterministic_tie_breaker() -> None:
    baseline = ResearchSessionEntry(
        label="baseline",
        manifest=make_manifest(run_id="run-1", objective_value=Decimal("1")),
    )
    candidate = ResearchSessionEntry(
        label="candidate",
        manifest=make_manifest(run_id="run-2", objective_value=Decimal("1")),
    )

    session = ResearchSession(
        session_id="session-1",
        name="Momentum Research",
        entries=(candidate, baseline),
    )

    assert session.best_entry is baseline


def test_research_session_with_entry_returns_new_session() -> None:
    first = ResearchSessionEntry(
        label="baseline",
        manifest=make_manifest(run_id="run-1"),
    )
    second = ResearchSessionEntry(
        label="candidate",
        manifest=make_manifest(run_id="run-2"),
    )

    session = ResearchSession(
        session_id="session-1",
        name="Momentum Research",
        entries=(first,),
    )

    updated = session.with_entry(second)

    assert session.entry_count == 1
    assert updated.entry_count == 2
    assert updated.entries == (first, second)


def test_research_session_rejects_duplicate_labels_and_run_ids() -> None:
    manifest = make_manifest()
    first = ResearchSessionEntry(label="baseline", manifest=manifest)
    duplicate_label = ResearchSessionEntry(
        label="baseline",
        manifest=make_manifest("run-2"),
    )
    duplicate_run = ResearchSessionEntry(label="candidate", manifest=manifest)

    with pytest.raises(ValueError, match="duplicate labels"):
        ResearchSession(
            session_id="session-1",
            name="Momentum Research",
            entries=(first, duplicate_label),
        )

    with pytest.raises(ValueError, match="duplicate run ids"):
        ResearchSession(
            session_id="session-1",
            name="Momentum Research",
            entries=(first, duplicate_run),
        )


def test_research_session_finds_entries() -> None:
    baseline = ResearchSessionEntry(
        label="baseline",
        manifest=make_manifest(run_id="run-1"),
        strategy_name="momentum",
    )
    candidate = ResearchSessionEntry(
        label="candidate",
        manifest=make_manifest(run_id="run-2"),
        strategy_name="mean_reversion",
    )

    session = ResearchSession(
        session_id="session-1",
        name="Research",
        entries=(baseline, candidate),
    )

    assert session.entry_for_label("baseline") is baseline
    assert session.entry_for_run_id("run-2") is candidate
    assert session.entries_for_strategy("momentum") == (baseline,)

    with pytest.raises(KeyError, match="unknown research session label"):
        session.entry_for_label("missing")

    with pytest.raises(KeyError, match="unknown research session run id"):
        session.entry_for_run_id("missing")


def test_research_session_builder_builds_from_manifests() -> None:
    builder = ResearchSessionBuilder(
        session_id="session-1",
        name="Momentum Research",
        description="research desk run",
        metadata={"owner": "quant"},
    )

    session = builder.build_from_manifests(
        {
            "baseline": make_manifest(run_id="run-1"),
            "candidate": make_manifest(run_id="run-2"),
        },
        strategy_name="momentum",
        metadata={"source": "sweep"},
    )

    assert session.session_id == "session-1"
    assert session.name == "Momentum Research"
    assert session.description == "research desk run"
    assert session.metadata == {"owner": "quant"}
    assert session.entry_count == 2
    assert tuple(entry.label for entry in session.entries) == (
        "baseline",
        "candidate",
    )
    assert all(entry.strategy_name == "momentum" for entry in session.entries)
    assert all(entry.metadata == {"source": "sweep"} for entry in session.entries)


def test_research_session_validates_required_values() -> None:
    manifest = make_manifest()

    with pytest.raises(ValueError, match="label"):
        ResearchSessionEntry(label=" ", manifest=manifest)

    with pytest.raises(ValueError, match="session_id"):
        ResearchSession(
            session_id=" ",
            name="Research",
            entries=(ResearchSessionEntry(label="baseline", manifest=manifest),),
        )

    with pytest.raises(ValueError, match="requires at least one entry"):
        ResearchSession(session_id="session-1", name="Research", entries=())
