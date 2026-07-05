from alpha.application.historical_ingestion import HistoricalIngestionService


def test_backfill_service_can_be_created() -> None:
    """
    Smoke test ensuring the service can be instantiated.
    """

    service = HistoricalIngestionService()

    assert service is not None
    assert callable(service.backfill)
