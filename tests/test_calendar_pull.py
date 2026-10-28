import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app import app
from features import calendar_pull
from routes.add_event_pull import _event_minimal, _event_when_parts


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
        self.assertEqual(minimal["date_label"], "Wed, Jul 15, 2026")

    def test_shape_event_exposes_end_time_and_location(self):
        event = calendar_pull._shape_event({
            "id": "evt-4",
            "title": "Policy briefing",
            "datetime_start": "2026-07-15 14:00:00",
            "datetime_end": "2026-07-15 15:30:00",
            "timezone": "America/New_York",
            "location": "Room 2123, Rayburn House Office Building",
        })

        self.assertEqual(event["end_time_text"], "3:30 PM EDT")
        self.assertEqual(event["location"], "Room 2123, Rayburn House Office Building")
        self.assertEqual(
            _event_when_parts(event),
            ("Wed, Jul 15, 2026", "2:00 PM EDT – 3:30 PM EDT"),
        )

    def test_ics_includes_event_location(self):
        event = calendar_pull._shape_event({
            "id": "evt-5",
            "title": "Policy briefing",
            "datetime_start": "2026-07-15 14:00:00",
            "datetime_end": "2026-07-15 15:00:00",
            "timezone": "America/New_York",
            "location": "Room 1, Main Building",
        })

        ics = calendar_pull.make_ics_for_event(event)

        self.assertIn("LOCATION:Room 1\\, Main Building", ics)


class CalendarPullPresentationTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY="calendar-pull-test")
        self.client = app.test_client()

    def test_event_list_uses_descriptive_links_instead_of_visible_urls(self):
        event = calendar_pull._shape_event({
            "id": "evt-presented",
            "title": "Health policy briefing",
            "description": "Details: https://example.com/events/a-very-long-written-out-link",
            "datetime_start": "2026-07-15 14:00:00",
            "datetime_end": "2026-07-15 15:30:00",
            "timezone": "America/New_York",
            "location": "Room 2123",
            "event_url": "https://app.addevent.com/event/evt-presented",
        })

        with patch("routes.add_event_pull.search_events_between", return_value=[event]):
            response = self.client.post(
                "/add-event-pull",
                data={"start_date": "2026-07-15", "end_date": "2026-07-15"},
            )

        self.assertEqual(response.status_code, 200)
        soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
        visible_text = soup.get_text(" ", strip=True)
        self.assertIn("Event details", visible_text)
        self.assertIn("Add to calendar", visible_text)
        self.assertIn("2:00 PM EDT – 3:30 PM EDT", visible_text)
        self.assertIn("Room 2123", visible_text)
        self.assertNotIn("https://example.com/events/a-very-long-written-out-link", visible_text)
        self.assertNotIn("ICS", visible_text)



if __name__ == "__main__":
    unittest.main()
