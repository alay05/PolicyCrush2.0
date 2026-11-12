import importlib
import unittest
from datetime import date
from unittest.mock import patch

from app import app
from sources.house.hearings import fetch_house_hearings


house_routes = importlib.import_module("routes.house")


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

    def test_house_tool_includes_selectable_house_hearings(self):
        app.config.update(TESTING=True, SECRET_KEY="house-hearing-test")
        client = app.test_client()
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
            patch.object(house_routes, "HOUSE_SOURCES", sources),
            patch.object(
                house_routes,
                "fetch_house_hearings",
                return_value={"Education and Workforce": [hearing]},
            ),
        ):
            response = client.post("/house", data={"start_date": "2026-11-01"})

        self.assertEqual(response.status_code, 200)
        with client.session_transaction() as current_session:
            results = current_session["manual_article_caches"]["house"]["results"]
            item = results["Education and Workforce"]["hearing"][0]
        self.assertIn(item["id"].encode(), response.data)
        self.assertEqual(item["section"], "hearing")
        self.assertEqual(item["date"], "2026-11-11T10:15:00-05:00")

        client.post("/saved-articles/add/house", data={"selected": item["id"]})
        with client.session_transaction() as current_session:
            self.assertEqual(current_session["saved_articles"], [item])


if __name__ == "__main__":
    unittest.main()
