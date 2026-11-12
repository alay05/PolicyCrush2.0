import importlib
import unittest
from datetime import datetime
from unittest.mock import patch

from app import app
from routes.saved_articles import prepare_article


news_routes = importlib.import_module("routes.news")
house_routes = importlib.import_module("routes.house")
senate_routes = importlib.import_module("routes.senate")


class SavedArticlesTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = app.test_client()

    def test_home_groups_newsletters_and_tools(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Newsletters", response.data)
        self.assertIn(b"Tools", response.data)
        self.assertIn(b"Main Newsletter", response.data)
        self.assertIn(b'href="/saved-articles"', response.data)
        self.assertIn(b"W2W4", response.data)
        self.assertIn(b'href="/add-event-pull"', response.data)
        self.assertIn(b"Daily", response.data)
        self.assertIn(b'href="/news"', response.data)
        self.assertIn(b"House", response.data)
        self.assertIn(b'href="/house"', response.data)
        self.assertIn(b"Senate", response.data)
        self.assertIn(b'href="/senate"', response.data)
        self.assertIn(b"AddEvent", response.data)
        self.assertIn(b'href="/add-event"', response.data)
        self.assertNotIn(b'href="/gmail"', response.data)
        self.assertNotIn(b">START<", response.data)
        self.assertEqual(self.client.get("/production/start").status_code, 200)

    def test_daily_selection_is_saved_once_and_can_be_removed(self):
        raw_article = {
            "title": "CMS update",
            "url": "https://example.com/cms-update",
            "date": "2026-10-20",
        }
        payload = {
            "url": "https://example.com/cms",
            "articles": [raw_article],
        }

        with patch.object(news_routes, "NEWS_SOURCES", {"CMS": lambda _: payload}):
            response = self.client.post("/news", data={"start_date": "2026-10-01"})

        article_id = prepare_article(raw_article, "news", "CMS")["id"]
        self.assertEqual(response.status_code, 200)
        self.assertIn(article_id.encode(), response.data)

        response = self.client.post(
            "/saved-articles/add/news",
            data={"selected": article_id},
            follow_redirects=True,
        )
        self.assertIn(b"Saved 1 article.", response.data)

        self.client.post(
            "/saved-articles/add/news",
            data={"selected": article_id},
        )
        with self.client.session_transaction() as current_session:
            self.assertEqual(len(current_session["saved_articles"]), 1)

        saved_page = self.client.get("/saved-articles")
        self.assertIn(b"CMS update", saved_page.data)
        self.assertIn("Daily — CMS".encode(), saved_page.data)

        removed = self.client.post(
            f"/saved-articles/{article_id}/remove",
            follow_redirects=True,
        )
        self.assertIn(b"No articles have been saved yet.", removed.data)

    def test_house_and_senate_results_are_normalized_and_saveable(self):
        house_article = {
            "title": "House release",
            "url": "https://example.com/house-release",
            "date": "2026-10-19",
        }
        house_hearing = {
            "title": "House hearing",
            "url": "https://example.com/house-hearing",
            "date": datetime(2026, 10, 22, 10, 0),
            "tag": "hearing",
        }
        senate_article = {
            "title": "Senate hearing",
            "url": "https://example.com/senate-hearing",
            "date": datetime(2026, 10, 21, 14, 30),
            "tag": "hearing",
        }

        house_sources = {
            "Appropriations": {
                "majority": lambda _: [house_article],
                "minority": lambda _: [],
            }
        }
        senate_sources = {
            "Finance": lambda _: {
                "base_url": "https://example.com/finance",
                "articles": [senate_article],
            }
        }

        with (
            patch.object(house_routes, "HOUSE_SOURCES", house_sources),
            patch.object(
                house_routes,
                "fetch_house_hearings",
                return_value={"Appropriations": [house_hearing]},
            ),
        ):
            house_page = self.client.post("/house", data={"start_date": "2026-10-01"})
        self.assertIn(
            b'href="https://appropriations.house.gov"',
            house_page.data,
        )
        house_id = prepare_article(house_article, "house", "Appropriations", "majority")["id"]
        house_hearing_id = prepare_article(
            house_hearing, "house", "Appropriations", "hearing"
        )["id"]
        self.client.post(
            "/saved-articles/add/house",
            data={"selected": [house_id, house_hearing_id]},
        )

        with (
            patch.object(senate_routes, "SENATE_SOURCES", senate_sources),
            patch.object(senate_routes, "fetch_senate_hearings", return_value={}),
        ):
            self.client.post("/senate", data={"start_date": "2026-10-01"})
        senate_id = prepare_article(senate_article, "senate", "Finance", "hearing")["id"]
        self.client.post("/saved-articles/add/senate", data={"selected": senate_id})

        saved_page = self.client.get("/saved-articles")
        self.assertIn("House — Appropriations — Majority".encode(), saved_page.data)
        self.assertIn("House — Appropriations — Hearing".encode(), saved_page.data)
        self.assertIn("Senate — Finance — Hearing".encode(), saved_page.data)
        self.assertLess(saved_page.data.index(b"Senate hearing"), saved_page.data.index(b"House release"))

        with self.client.session_transaction() as current_session:
            hearing = next(
                article
                for article in current_session["saved_articles"]
                if article["id"] == senate_id
            )
            self.assertEqual(hearing["date"], "2026-10-21T14:30:00")

    def test_manual_article_is_saved_with_all_fields_before_headline_actions(self):
        response = self.client.post(
            "/saved-articles/manual",
            data={
                "title": "Senate Finance Committee Holds Rural Health Hearing",
                "source": "Senate Finance Committee",
                "url": "https://example.com/rural-health-hearing",
                "date": "2026-11-05",
                "time": "10:30",
                "section": "hearing",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Manual article saved.", response.data)
        self.assertIn(b"Senate Finance Committee Holds Rural Health Hearing", response.data)
        self.assertIn(
            "Manual — Senate Finance Committee — Hearing".encode(),
            response.data,
        )
        self.assertLess(
            response.data.index(b"Senate Finance Committee Holds Rural Health Hearing"),
            response.data.index(b"Add an Article Manually"),
        )
        self.assertLess(
            response.data.index(b"Add an Article Manually"),
            response.data.index(b"Generate Headlines"),
        )

        with self.client.session_transaction() as current_session:
            article = current_session["saved_articles"][0]
        self.assertEqual(article["tool"], "manual")
        self.assertEqual(article["source"], "Senate Finance Committee")
        self.assertEqual(article["section"], "hearing")
        self.assertEqual(article["date"], "2026-11-05T10:30:00")

    def test_manual_article_is_processed_by_existing_headline_workflow(self):
        self.client.post(
            "/saved-articles/manual",
            data={
                "title": "CMS releases a new Medicare policy",
                "url": "https://example.com/manual-cms-policy",
                "date": "2026-11-03",
                "section": "",
            },
        )
        with self.client.session_transaction() as current_session:
            article = current_session["saved_articles"][0]

        generated = [
            {
                "id": article["id"],
                "headline": "CMS Releases New Medicare Policy",
                "link_text": "Releases",
                "category": "Medicare",
            }
        ]
        with patch(
            "headlines.routes.generate_headline_records",
            return_value=generated,
        ) as generate_mock:
            response = self.client.post("/headlines/generate", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"CMS Releases New Medicare Policy", response.data)
        requested_article = generate_mock.call_args.args[0][0]
        self.assertEqual(requested_article["id"], article["id"])
        self.assertEqual(requested_article["tool"], "manual")
        self.assertEqual(requested_article["source"], "")
        self.assertEqual(requested_article["source_label"], "Manual")

    def test_manual_article_rejects_invalid_links_and_duplicate_urls(self):
        invalid = self.client.post(
            "/saved-articles/manual",
            data={
                "title": "Unsafe article",
                "source": "Example",
                "url": "javascript:alert(1)",
                "date": "2026-11-03",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Enter a valid article link", invalid.data)
        with self.client.session_transaction() as current_session:
            self.assertFalse(current_session.get("saved_articles"))

        payload = {
            "title": "Manual article",
            "source": "Example",
            "url": "https://example.com/manual-article",
            "date": "2026-11-03",
        }
        self.client.post("/saved-articles/manual", data=payload)
        duplicate = self.client.post(
            "/saved-articles/manual",
            data={**payload, "title": "Duplicate title"},
            follow_redirects=True,
        )

        self.assertIn(b"That article is already saved.", duplicate.data)
        with self.client.session_transaction() as current_session:
            self.assertEqual(len(current_session["saved_articles"]), 1)

    def test_saved_articles_are_isolated_by_session(self):
        with self.client.session_transaction() as current_session:
            current_session["saved_articles"] = [
                prepare_article(
                    {
                        "title": "Private session item",
                        "url": "https://example.com/private",
                        "date": "2026-10-21",
                    },
                    "news",
                    "CMS",
                )
            ]

        self.assertIn(b"Private session item", self.client.get("/saved-articles").data)
        other_client = app.test_client()
        self.assertNotIn(b"Private session item", other_client.get("/saved-articles").data)


if __name__ == "__main__":
    unittest.main()
