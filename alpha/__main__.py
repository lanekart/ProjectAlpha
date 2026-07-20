from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "historical-truth":
        from alpha.historical_truth.cli import historical_truth_app

        sys.argv.pop(1)
        historical_truth_app()
        return

    from alpha.cli import app

    app()


if __name__ == "__main__":
    main()
