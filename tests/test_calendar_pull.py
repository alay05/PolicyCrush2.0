import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from features import calendar_pull
from routes.add_event_pull import _event_minimal


class CalendarPullEventTimeTests(unittest.TestCase):
    def setUp(self):
        self.original_local_tz = calendar_pull.LOCAL_TZ
        calendar_pull.LOCAL_TZ = ZoneInfo("America/New_York")

    def tearDown(self):
        calendar_pull.LOCAL_TZ = self.original_local_tz

    def test_shape_event_exposes_local_start_time(self):
        event = calendar_pull._shape_event({
            "id": "evt-1",
            "title": "Policy briefing",
            "datetime_start": "2026-01-21 09:30:00",
            "datetime_end": "2026-01-21 10:30:00",
            "timezone": "America/New_York",
            "all_day_event": False,
        })

        self.assertIsInstance(event["starts_at_dt"], datetime)
        self.assertEqual(event["date_text"], "2026-01-21")
        self.assertIn("9:30 AM", event["time_text"])

    def test_shape_event_labels_all_day_events(self):
        event = calendar_pull._shape_event({
            "id": "evt-2",
            "title": "Submission deadline",
            "datetime_start": "2026-01-21",
            "timezone": "America/New_York",
            "all_day_event": True,
        })

        self.assertEqual(event["time_text"], "All day")

    def test_shape_event_converts_event_timezone_to_local_timezone(self):
        event = calendar_pull._shape_event({
            "id": "evt-pacific",
            "title": "West coast briefing",
            "datetime_start": "2026-01-21 09:30:00",
            "timezone": "America/Los_Angeles",
        })

        self.assertEqual(event["time_text"], "12:30 PM EST")

    def test_minimal_event_keeps_date_and_time_for_review(self):
        event = calendar_pull._shape_event({
            "id": "evt-3",
            "title": "Committee hearing",
            "datetime_start": "2026-07-15 14:00:00",
            "timezone": "America/New_York",
        })

        minimal = _event_minimal(event)

        self.assertEqual(minimal["date"], "2026-07-15 2:00 PM EDT")


if __name__ == "__main__":
    unittest.main()
