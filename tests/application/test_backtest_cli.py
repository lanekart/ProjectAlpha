from datetime import date

from alpha.cli import _parse_date


def test_parse_date() -> None:
    assert _parse_date("2024-01-15") == date(2024, 1, 15)
