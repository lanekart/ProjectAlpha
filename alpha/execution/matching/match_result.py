from __future__ import annotations

from dataclasses import dataclass

from alpha.execution.fill import Fill
from alpha.execution.matching.enums import MatchType


@dataclass(frozen=True)
class MatchResult:
    match_type: MatchType
    fills: tuple[Fill, ...]
