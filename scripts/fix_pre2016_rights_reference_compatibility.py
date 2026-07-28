from __future__ import annotations

from pathlib import Path

ENGINE = Path("alpha/historical_truth/complete_corporate_action_engine.py")


def replace_once(text: str, old: str, new: str, code: str) -> str:
    if old not in text:
        raise RuntimeError(code)
    return text.replace(old, new, 1)


def main() -> None:
    text = ENGINE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    joins: dict[str, dict[str, Any]],\n",
        "    joins: dict[str, dict[str, Any]] | None = None,\n",
        "RIGHTS_REFERENCE_OPTIONAL_JOIN_SIGNATURE_MISSING",
    )
    text = replace_once(
        text,
        '''            if source.action_type is CorporateActionType.RIGHTS:
                reference, provenance = _rights_reference_context(
                    connection,
                    source=source,
                    event=event,
                    join=joins.get(str(event["governed_identity_id"]), {}),
                )
''',
        '''            if source.action_type is CorporateActionType.RIGHTS:
                if joins is None:
                    row = connection.execute(
                        "SELECT close_price FROM daily_candle WHERE symbol=? AND "
                        "series=? AND trading_date<? ORDER BY trading_date DESC LIMIT 1",
                        [source.symbol, source.series, source.effective_date],
                    ).fetchone()
                    reference = float(row[0]) if row else None
                    provenance = {
                        "reference_price_date": None,
                        "reference_price_series": source.series.upper(),
                        "reference_price_isin": None,
                        "reference_price_source_sha256": None,
                        "reference_price_provenance_state": (
                            "LEGACY_UNCERTIFIED_REFERENCE_PRICE"
                            if reference is not None
                            else "PRIOR_CANDLE_MISSING"
                        ),
                        "reference_price_certified": False,
                    }
                else:
                    reference, provenance = _rights_reference_context(
                        connection,
                        source=source,
                        event=event,
                        join=joins.get(str(event["governed_identity_id"]), {}),
                    )
''',
        "RIGHTS_REFERENCE_OPTIONAL_JOIN_CALL_MISSING",
    )
    ENGINE.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
