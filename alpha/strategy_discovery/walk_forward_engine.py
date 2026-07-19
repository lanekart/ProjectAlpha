from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from alpha.strategy_discovery.models import (
    DiscoveryDataset,
    DiscoveryRow,
    DiscoveryRunConfig,
    WalkForwardFold,
)


@dataclass(frozen=True, slots=True)
class ChronologicalPartition:
    training_rows: tuple[DiscoveryRow, ...]
    validation_rows: tuple[DiscoveryRow, ...]
    holdout_rows: tuple[DiscoveryRow, ...]
    folds: tuple[WalkForwardFold, ...]


class WalkForwardEngine:
    """Build chronological, purged, expanding validation folds."""

    def partition(
        self,
        *,
        dataset: DiscoveryDataset,
        config: DiscoveryRunConfig,
    ) -> ChronologicalPartition:
        dates = tuple(sorted({row.candidate_timestamp.date() for row in dataset.rows}))
        if len(dates) < 5:
            raise ValueError("at least five distinct decision dates are required")
        validation_count = max(1, len(dates) * config.validation_fraction_pct // 100)
        holdout_count = max(1, len(dates) * config.holdout_fraction_pct // 100)
        training_count = len(dates) - validation_count - holdout_count
        if training_count < 1:
            raise ValueError("chronological split leaves no training period")
        validation_start = dates[training_count]
        holdout_start = dates[training_count + validation_count]
        purge_boundary = validation_start - timedelta(days=config.purge_gap_days)
        training = tuple(
            row
            for row in dataset.rows
            if row.candidate_timestamp.date() < purge_boundary
        )
        validation = tuple(
            row
            for row in dataset.rows
            if validation_start <= row.candidate_timestamp.date() < holdout_start
        )
        holdout = tuple(
            row
            for row in dataset.rows
            if row.candidate_timestamp.date() >= holdout_start
        )
        folds = self._folds(
            dataset.rows,
            pre_holdout_dates=dates[: training_count + validation_count],
            purge_gap_days=config.purge_gap_days,
        )
        return ChronologicalPartition(
            training_rows=training,
            validation_rows=validation,
            holdout_rows=holdout,
            folds=folds,
        )

    def _folds(
        self,
        rows: tuple[DiscoveryRow, ...],
        *,
        pre_holdout_dates: tuple[date, ...],
        purge_gap_days: int,
    ) -> tuple[WalkForwardFold, ...]:
        if len(pre_holdout_dates) < 4:
            return ()
        initial_training = max(1, len(pre_holdout_dates) // 2)
        remaining = len(pre_holdout_dates) - initial_training
        window = max(1, remaining // 3)
        folds: list[WalkForwardFold] = []
        for index in range(3):
            validation_start_index = initial_training + (index * window)
            if validation_start_index >= len(pre_holdout_dates):
                break
            validation_end_index = min(
                len(pre_holdout_dates), validation_start_index + window
            )
            validation_dates = pre_holdout_dates[
                validation_start_index:validation_end_index
            ]
            if not validation_dates:
                continue
            validation_start = validation_dates[0]
            purge_boundary = validation_start - timedelta(days=purge_gap_days)
            training_rows = tuple(
                row for row in rows if row.candidate_timestamp.date() < purge_boundary
            )
            validation_rows = tuple(
                row
                for row in rows
                if validation_dates[0]
                <= row.candidate_timestamp.date()
                <= validation_dates[-1]
            )
            if not training_rows or not validation_rows:
                continue
            folds.append(
                WalkForwardFold(
                    fold_id=f"WF-{index + 1}",
                    training_start=training_rows[0].candidate_timestamp.date(),
                    training_end=training_rows[-1].candidate_timestamp.date(),
                    validation_start=validation_dates[0],
                    validation_end=validation_dates[-1],
                    purge_gap_days=purge_gap_days,
                    training_candidate_ids=tuple(
                        row.candidate_id for row in training_rows
                    ),
                    validation_candidate_ids=tuple(
                        row.candidate_id for row in validation_rows
                    ),
                )
            )
        return tuple(folds)


__all__ = ["ChronologicalPartition", "WalkForwardEngine"]
