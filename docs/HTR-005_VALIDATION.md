# HTR-005 Validation Gates

HTR-005 is complete only when the final branch head passes all of the following
without local modifications:

```bash
poetry run ruff check . && \
poetry run ruff format --check . && \
poetry run mypy alpha && \
poetry run pytest -q
```

The governed replay acceptance evidence must also show:

- decision-date reads use the replay date as their `as_of` cutoff;
- historical decision inputs cannot use future corporate-action knowledge;
- future outcome frames begin after the decision date;
- current and historical tickers resolve to one stable security identity;
- unresolved material actions fail closed;
- production replay commands require explicit HTR-002 and HTR-003 artifacts;
- replay outputs are coupled to deterministic input, frame, and run hashes; and
- no production module constructs `HistoricalObservationFactory` directly.

GitHub Lint and CI and an independent local full-repository run are both required
before PR #11 can be merged.
