from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, NamedTuple


JST = timezone(timedelta(hours=9), name="JST")
LifecycleEventName = Literal["wake", "sleep_warning", "sleep"]


class LifecycleEvent(NamedTuple):
    at: datetime
    name: LifecycleEventName


def next_daily_time(
    now: datetime,
    *,
    hour: int,
    minute: int,
) -> datetime:
    local_now = now.astimezone(JST)
    target = local_now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )
    if target <= local_now:
        target += timedelta(days=1)
    return target


def next_sleep_warning_time(now: datetime) -> datetime:
    local_now = now.astimezone(JST)
    warning_start = local_now.replace(
        hour=23,
        minute=25,
        second=0,
        microsecond=0,
    )
    shutdown = warning_start + timedelta(minutes=5)
    if warning_start <= local_now < shutdown:
        return local_now
    return next_daily_time(local_now, hour=23, minute=25)


def is_sleeping_time(now: datetime) -> bool:
    local_now = now.astimezone(JST)
    minutes = local_now.hour * 60 + local_now.minute
    return minutes >= 23 * 60 + 30 or minutes < 6 * 60


def next_lifecycle_event(now: datetime) -> LifecycleEvent:
    local_now = now.astimezone(JST)
    candidates: list[LifecycleEvent] = []
    schedule: tuple[tuple[int, int, LifecycleEventName], ...] = (
        (6, 0, "wake"),
        (23, 25, "sleep_warning"),
        (23, 30, "sleep"),
    )
    for day_offset in (0, 1):
        day = local_now + timedelta(days=day_offset)
        for hour, minute, name in schedule:
            target = day.replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )
            if target > local_now:
                candidates.append(LifecycleEvent(target, name))
    return min(candidates, key=lambda event: event.at)
