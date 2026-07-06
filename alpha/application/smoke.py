from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class SmokeInput:
    symbol: str
    close: Decimal
    previous_close: Decimal


@dataclass(frozen=True, slots=True)
class SmokeResult:
    symbol: str
    close: Decimal
    previous_close: Decimal
    return_pct: Decimal
    signal: str


@dataclass(frozen=True, slots=True)
class SmokeReport:
    results: tuple[SmokeResult, ...]

    @property
    def processed(self) -> int:
        return len(self.results)

    @property
    def buy_count(self) -> int:
        return sum(1 for result in self.results if result.signal == "BUY")

    @property
    def sell_count(self) -> int:
        return sum(1 for result in self.results if result.signal == "SELL")

    @property
    def hold_count(self) -> int:
        return sum(1 for result in self.results if result.signal == "HOLD")

    def render(self) -> str:
        lines = [
            "Project Alpha Smoke Report",
            "",
            f"Processed: {self.processed}",
            f"BUY: {self.buy_count}",
            f"HOLD: {self.hold_count}",
            f"SELL: {self.sell_count}",
            "",
            "Top Results:",
        ]

        for index, result in enumerate(self.results, start=1):
            lines.append(
                f"{index}. {result.symbol} | "
                f"close={result.close} | "
                f"return={result.return_pct:.2f}% | "
                f"signal={result.signal}"
            )

        return "\n".join(lines)


class SmokeApplication:
    def run(self, inputs: Iterable[SmokeInput]) -> SmokeReport:
        results = tuple(
            sorted(
                (self._evaluate(item) for item in inputs),
                key=lambda result: result.return_pct,
                reverse=True,
            )
        )
        return SmokeReport(results=results)

    def _evaluate(self, item: SmokeInput) -> SmokeResult:
        if item.previous_close <= Decimal("0"):
            raise ValueError("previous_close must be greater than zero")

        price_change = item.close - item.previous_close
        return_pct = price_change / item.previous_close * Decimal("100")

        if return_pct >= Decimal("2"):
            signal = "BUY"
        elif return_pct <= Decimal("-2"):
            signal = "SELL"
        else:
            signal = "HOLD"

        return SmokeResult(
            symbol=item.symbol,
            close=item.close,
            previous_close=item.previous_close,
            return_pct=return_pct,
            signal=signal,
        )


def build_default_smoke_inputs() -> Sequence[SmokeInput]:
    return (
        SmokeInput("RELIANCE", Decimal("2940"), Decimal("2870")),
        SmokeInput("TCS", Decimal("4025"), Decimal("4000")),
        SmokeInput("HDFCBANK", Decimal("1710"), Decimal("1725")),
        SmokeInput("INFY", Decimal("1580"), Decimal("1530")),
        SmokeInput("ICICIBANK", Decimal("1210"), Decimal("1245")),
    )


def run_smoke_application() -> SmokeReport:
    return SmokeApplication().run(build_default_smoke_inputs())
