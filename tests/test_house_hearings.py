import unittest
from datetime import date
from unittest.mock import patch

import production.adapters as production_adapters
from sources.house.hearings import fetch_house_hearings


class HouseHearingTests(unittest.TestCase):
    @patch("sources.house.hearings.fetch_committee_hearings")
    @patch("sources.house.hearings._fetch_house_calendar")
    def test_house_and_joint_calendars_are_combined(self, house_calendar, fetch):
        house_calendar.return_value = {
            "Appropriations": [{"title": "House hearing"}],
            "Joint Economic": [],
        }
        fetch.return_value = {"Joint Economic": [{"title": "Joint hearing"}]}

        grouped = fetch_house_hearings(date(2026, 1, 1))

        self.assertEqual(grouped["Appropriations"][0]["title"], "House hearing")
        self.assertEqual(grouped["Joint Economic"][0]["title"], "Joint hearing")
        self.assertEqual(fetch.call_args.args[0], "joint")

    def test_production_bundle_includes_selectable_house_hearings(self):
        hearing = {
            "title": "Committee hearing",
            "url": "https://www.congress.gov/event/119th-Congress/house-event/100",
            "date": "2026-11-11T10:15:00-05:00",
        }
        sources = {
            "Education and Workforce": {
                "majority": lambda _: [],
                "minority": lambda _: [],
            }
        }
        with (
            patch.object(production_adapters, "HOUSE_SOURCES", sources),
            patch.object(
                production_adapters,
                "fetch_house_hearings",
                return_value={"Education and Workforce": [hearing]},
            ),
        ):
            bundle = production_adapters.fetch_house_bundle(date(2026, 11, 1))

        item = bundle["Education and Workforce"]["hearing"][0]
        self.assertEqual(item["tag"], "hearing")
        self.assertEqual(item["side"], "hearing")
        self.assertEqual(item["date"], "2026-11-11T10:15:00-05:00")


if __name__ == "__main__":
    unittest.main()
