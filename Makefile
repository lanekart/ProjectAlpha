.PHONY: lint typecheck test-fast test-affected test-historical-truth test-b1g test-b1-final test-full validate-fast validate-milestone

PYTEST := poetry run pytest

lint:
	poetry run ruff check .
	poetry run ruff format --check .

typecheck:
	poetry run mypy alpha

test-fast:
	$(PYTEST) -q -m "not slow and not network"

test-affected:
	poetry run python scripts/select_tests.py --run

test-historical-truth:
	$(PYTEST) -q tests/historical_truth

test-b1g:
	$(PYTEST) -q \
		tests/historical_truth/test_official_bridge_reconciliation.py \
		tests/historical_truth/test_official_bridge_reconciliation_cli.py \
		tests/historical_truth/test_official_bridge_reconciliation_integration.py

test-b1-final:
	$(PYTEST) -q tests/historical_truth/test_b1_final_closure.py

test-full:
	$(PYTEST) -q

validate-fast: lint test-affected

validate-milestone: lint typecheck test-historical-truth
