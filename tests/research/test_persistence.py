from decimal import Decimal

import pytest

from alpha.research import (
    InMemoryResearchExperimentRepository,
    ParameterCombination,
    ParameterSweepReport,
    ParameterSweepResult,
    ResearchExperimentManifest,
    ResearchExperimentPersistenceService,
    ResearchExperimentRecord,
    WalkForwardReport,
    WalkForwardResult,
    WalkForwardWindow,
)


def make_walk_forward_report(
    metric: str = "score",
    value: Decimal = Decimal("1"),
) -> WalkForwardReport:
    return WalkForwardReport(
        results=(
            WalkForwardResult(
                window=WalkForwardWindow(
                    index=0,
                    train_start=0,
                    train_end=5,
                    test_start=5,
                    test_end=6,
                ),
                metrics={metric: value},
            ),
        )
    )


def make_sweep_report() -> ParameterSweepReport:
    first = ParameterSweepResult(
        combination=ParameterCombination(
            experiment_id="exp_0000__lookback-20",
            values={"lookback": 20},
        ),
        report=make_walk_forward_report(value=Decimal("2")),
        objective_metric="score",
        objective_value=Decimal("2"),
    )
    second = ParameterSweepResult(
        combination=ParameterCombination(
            experiment_id="exp_0001__lookback-10",
            values={"lookback": 10},
        ),
        report=make_walk_forward_report(value=Decimal("1")),
        objective_metric="score",
        objective_value=Decimal("1"),
    )
    return ParameterSweepReport(results=(first, second), objective_metric="score")


def test_experiment_record_copies_and_validates_values() -> None:
    record = ResearchExperimentRecord(
        experiment_id=" exp_0000 ",
        parameters={"lookback": 20},
        objective_metric=" score ",
        objective_value=Decimal("2"),
        rank=1,
        metadata={"suite": "unit"},
    )

    assert record.experiment_id == "exp_0000"
    assert record.objective_metric == "score"
    assert record.parameters == {"lookback": 20}
    assert record.metadata == {"suite": "unit"}


def test_manifest_exposes_count_and_best_record() -> None:
    record = ResearchExperimentRecord(
        experiment_id="exp_0000",
        parameters={"lookback": 20},
        objective_metric="score",
        objective_value=Decimal("2"),
        rank=1,
    )

    manifest = ResearchExperimentManifest(
        run_id=" run-1 ",
        objective_metric=" score ",
        records=(record,),
        metadata={"kind": "parameter_sweep"},
    )

    assert manifest.run_id == "run-1"
    assert manifest.record_count == 1
    assert manifest.best_record is record
    assert manifest.metadata["kind"] == "parameter_sweep"


def test_in_memory_repository_saves_and_loads_manifest() -> None:
    repository = InMemoryResearchExperimentRepository()
    record = ResearchExperimentRecord(
        experiment_id="exp_0000",
        parameters={"lookback": 20},
        objective_metric="score",
        objective_value=Decimal("2"),
        rank=1,
    )
    manifest = ResearchExperimentManifest(
        run_id="run-1",
        objective_metric="score",
        records=(record,),
    )

    repository.save(manifest)

    assert repository.contains("run-1")
    assert repository.load("run-1") is manifest


def test_persistence_service_persists_parameter_sweep_report() -> None:
    repository = InMemoryResearchExperimentRepository()
    service = ResearchExperimentPersistenceService(repository=repository)

    manifest = service.persist_parameter_sweep(
        run_id="sweep-1",
        report=make_sweep_report(),
        metadata={"owner": "research"},
    )

    assert repository.load("sweep-1") is manifest
    assert manifest.objective_metric == "score"
    assert manifest.record_count == 2
    assert manifest.best_record.experiment_id == "exp_0000__lookback-20"
    assert manifest.best_record.objective_value == Decimal("2")
    assert tuple(record.rank for record in manifest.records) == (1, 2)
    assert manifest.metadata["owner"] == "research"


def test_repository_rejects_unknown_run_id() -> None:
    repository = InMemoryResearchExperimentRepository()

    with pytest.raises(KeyError, match="unknown research experiment run"):
        repository.load("missing")


def test_persistence_value_objects_validate_inputs() -> None:
    with pytest.raises(ValueError, match="experiment_id"):
        ResearchExperimentRecord(
            experiment_id=" ",
            parameters={"lookback": 20},
            objective_metric="score",
            objective_value=Decimal("2"),
            rank=1,
        )

    with pytest.raises(ValueError, match="rank"):
        ResearchExperimentRecord(
            experiment_id="exp_0000",
            parameters={"lookback": 20},
            objective_metric="score",
            objective_value=Decimal("2"),
            rank=0,
        )

    record = ResearchExperimentRecord(
        experiment_id="exp_0000",
        parameters={"lookback": 20},
        objective_metric="score",
        objective_value=Decimal("2"),
        rank=2,
    )
    with pytest.raises(ValueError, match="contiguous rank"):
        ResearchExperimentManifest(
            run_id="run-1",
            objective_metric="score",
            records=(record,),
        )

    other_metric_record = ResearchExperimentRecord(
        experiment_id="exp_0000",
        parameters={"lookback": 20},
        objective_metric="other",
        objective_value=Decimal("2"),
        rank=1,
    )
    with pytest.raises(ValueError, match="manifest objective metric"):
        ResearchExperimentManifest(
            run_id="run-1",
            objective_metric="score",
            records=(other_metric_record,),
        )
