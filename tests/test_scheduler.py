from __future__ import annotations

import unittest
from datetime import datetime, timezone

from god_bot.scheduler import (
    is_sleeping_time,
    next_daily_time,
    next_lifecycle_event,
    next_sleep_warning_time,
)


class SchedulerTests(unittest.TestCase):
    def test_returns_same_days_sleep_warning_in_jst(self) -> None:
        now = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)
        target = next_daily_time(now, hour=23, minute=25)
        self.assertEqual(
            target.isoformat(),
            "2026-07-27T23:25:00+09:00",
        )

    def test_rolls_past_time_to_next_day(self) -> None:
        now = datetime(2026, 7, 27, 14, 26, tzinfo=timezone.utc)
        target = next_daily_time(now, hour=23, minute=25)
        self.assertEqual(
            target.isoformat(),
            "2026-07-28T23:25:00+09:00",
        )

    def test_sleep_warning_catches_up_before_shutdown(self) -> None:
        now = datetime(2026, 7, 27, 14, 28, tzinfo=timezone.utc)
        target = next_sleep_warning_time(now)
        self.assertEqual(target, now.astimezone(target.tzinfo))

    def test_sleep_warning_does_not_run_at_shutdown(self) -> None:
        now = datetime(2026, 7, 27, 14, 30, tzinfo=timezone.utc)
        target = next_sleep_warning_time(now)
        self.assertEqual(
            target.isoformat(),
            "2026-07-28T23:25:00+09:00",
        )

    def test_sleep_mode_covers_2330_through_0600_jst(self) -> None:
        self.assertTrue(
            is_sleeping_time(
                datetime(2026, 7, 27, 14, 30, tzinfo=timezone.utc)
            )
        )
        self.assertTrue(
            is_sleeping_time(
                datetime(2026, 7, 27, 20, 59, tzinfo=timezone.utc)
            )
        )
        self.assertFalse(
            is_sleeping_time(
                datetime(2026, 7, 27, 21, 0, tzinfo=timezone.utc)
            )
        )

    def test_lifecycle_events_progress_warning_sleep_wake(self) -> None:
        warning = next_lifecycle_event(
            datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(warning.name, "sleep_warning")
        self.assertEqual(warning.at.hour, 23)
        self.assertEqual(warning.at.minute, 25)

        sleep = next_lifecycle_event(
            datetime(2026, 7, 27, 14, 29, tzinfo=timezone.utc)
        )
        self.assertEqual(sleep.name, "sleep")
        catch_up_complete = next_lifecycle_event(
            datetime(2026, 7, 27, 14, 29, 59, 999999, tzinfo=timezone.utc)
        )
        self.assertEqual(catch_up_complete.name, "sleep")

        wake = next_lifecycle_event(
            datetime(2026, 7, 27, 14, 30, tzinfo=timezone.utc)
        )
        self.assertEqual(wake.name, "wake")
        self.assertEqual(wake.at.hour, 6)


if __name__ == "__main__":
    unittest.main()
