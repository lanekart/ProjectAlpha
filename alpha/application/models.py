from dataclasses import dataclass


@dataclass(slots=True)
class BackfillResult:
    """
    Summary of a historical ingestion run.
    """

    processed: int
    skipped: int
    failed: int
