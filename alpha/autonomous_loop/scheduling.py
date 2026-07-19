from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

from alpha.autonomous_loop.models import ScheduleDefinition


class ScheduleEvaluator:
    """Resolve deterministic due slots for an externally invoked scheduler tick."""

    def due_slot(
        self, schedule: ScheduleDefinition, *, now: datetime
    ) -> datetime | None:
        if not schedule.enabled:
            return None
        aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        local_now = aware.astimezone(ZoneInfo(schedule.timezone))
        if local_now.weekday() not in schedule.weekdays:
            return None
        local_slot = datetime.combine(
            local_now.date(),
            schedule.local_time,
            tzinfo=ZoneInfo(schedule.timezone),
        )
        if local_now < local_slot:
            return None
        return local_slot.astimezone(UTC)

    def run_id(self, schedule: ScheduleDefinition, slot: datetime) -> str:
        normalized = slot if slot.tzinfo is not None else slot.replace(tzinfo=UTC)
        digest = sha256(
            (
                f"{schedule.schedule_id}|{schedule.version}|"
                f"{normalized.astimezone(UTC).isoformat()}"
            ).encode()
        ).hexdigest()[:20]
        return f"autonomous-{digest}"


__all__ = ["ScheduleEvaluator"]
