import unittest
from datetime import date
from unittest.mock import patch

from sources.congress_meetings import fetch_committee_hearings


class CongressMeetingTests(unittest.TestCase):
    @patch("sources.congress_meetings._sync_meetings")
    def test_only_hearings_for_tracked_parent_and_subcommittees_are_returned(self, sync):
        sync.return_value = [
            {
                "detail": {
                    "eventId": "338804",
                    "type": "Open Hearing",
                    "title": "Tax policy oversight",
                    "date": "2026-11-10T15:30:00Z",
                    "meetingStatus": "Scheduled",
                    "committees": [{"systemCode": "ssfi13"}],
                }
            },
            {
                "detail": {
                    "eventId": "338805",
                    "type": "Open Business Meeting",
                    "title": "Executive session",
                    "date": "2026-11-10T15:30:00Z",
                    "committees": [{"systemCode": "ssfi00"}],
                }
            },
            {
                "detail": {
                    "eventId": "338806",
                    "type": "Open Hearing",
                    "title": "Untracked committee hearing",
                    "date": "2026-11-10T15:30:00Z",
                    "committees": [{"systemCode": "ssfr00"}],
                }
            },
        ]

        grouped = fetch_committee_hearings(
            "senate",
            {"ssfi": "Finance"},
            date(2026, 1, 1),
            today=date(2026, 11, 9),
        )

        self.assertEqual(len(grouped["Finance"]), 1)
        hearing = grouped["Finance"][0]
        self.assertEqual(hearing["title"], "Tax policy oversight")
        self.assertEqual(hearing["date"].isoformat(), "2026-11-10T10:30:00-05:00")
        self.assertEqual(
            hearing["url"],
            "https://www.congress.gov/event/119th-Congress/senate-event/338804",
        )


if __name__ == "__main__":
    unittest.main()
