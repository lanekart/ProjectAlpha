from enum import StrEnum


class PositionStatus(StrEnum):
    OPEN = "OPEN"
    EXIT_REQUESTED = "EXIT_REQUESTED"
    WAITING_LIQUIDITY = "WAITING_LIQUIDITY"
    PARTIAL = "PARTIAL"
    CLOSED = "CLOSED"


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class ExitReason(StrEnum):
    TARGET = "TARGET"
    STOP = "STOP"
    SIGNAL = "SIGNAL"
    TIME = "TIME"
    MANUAL = "MANUAL"
    UNKNOWN = "UNKNOWN"
