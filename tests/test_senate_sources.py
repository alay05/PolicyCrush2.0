import unittest
from datetime import date
from unittest.mock import Mock, patch

import requests

from sources.senate.budget import fetch_budg_articles
from sources.senate.common import get_senate_page
from sources.senate.finance import fetch_fin_articles
from sources.senate.indian import fetch_ind_articles


def response(html):
    result = Mock()
    result.status_code = 200
    result.text = html
    return result


def listing(path, title="Official item", value="September 24, 2026 at 2:30 PM"):
    return f"""
    <article>
      <div class="published-date">{value}</div>
      <h2><a href="{path}">{title}</a></h2>
    </article>
    """


def requests_response(url, html):
    result = requests.Response()
    result.status_code = 200
    result.url = url
    result.encoding = "utf-8"
    result._content = html.encode("utf-8")
    return result


class SenateSourceTests(unittest.TestCase):
    @patch("sources.senate.common.fetch_response")
    def test_listing_pagination_stops_after_crossing_start_date(self, get):
        get.side_effect = [
            requests_response(
                "https://committee.senate.gov/news",
                listing("/news/item-1", value="February 2, 2026")
                + '<a href="?page=2">Next</a>',
            ),
            requests_response(
                "https://committee.senate.gov/news?page=2",
                listing("/news/item-2", value="December 20, 2025")
                + '<a href="?page=3">Next</a>',
            ),
        ]

        result = get_senate_page(
            "https://committee.senate.gov/news",
            start_date=date(2026, 1, 1),
        )

        self.assertEqual(get.call_count, 2)
        self.assertIn("item-1", result.text)
        self.assertIn("item-2", result.text)

    @patch("sources.senate.finance.get_senate_page")
    def test_finance_uses_current_newsroom_urls_and_parses_current_cards(self, get):
        get.side_effect = [
            response(listing("/newsroom/chairmans-news/majority-item")),
            response(listing("/newsroom/ranking-members-news/minority-item")),
        ]

        result = fetch_fin_articles(date(2026, 1, 1))

        self.assertEqual(
            [call.args[0] for call in get.call_args_list],
            [
                "https://www.finance.senate.gov/newsroom/chairmans-news/",
                "https://www.finance.senate.gov/newsroom/ranking-members-news/",
            ],
        )
        self.assertEqual([item["tag"] for item in result["articles"]], ["majority", "minority"])

    @patch("sources.senate.budget.get_senate_page")
    def test_budget_uses_current_press_release_pages(self, get):
        get.return_value = response("")

        fetch_budg_articles(date(2026, 1, 1))

        self.assertEqual(
            [call.args[0] for call in get.call_args_list[:2]],
            [
                "https://www.budget.senate.gov/chairman/newsroom/press/?press_type=press_release",
                "https://www.budget.senate.gov/ranking-member/newsroom/press/?press_type=press_release",
            ],
        )

    @patch("sources.senate.indian.get_senate_page")
    def test_indian_affairs_uses_current_archives_and_hearings(self, get):
        get.side_effect = [
            response(listing("/newsroom/press-release/republican/majority-item/")),
            response(listing("/newsroom/press-release/democratic/minority-item/")),
        ]

        result = fetch_ind_articles(date(2026, 1, 1))

        self.assertEqual(
            [call.args[0] for call in get.call_args_list],
            [
                "https://www.indian.senate.gov/newsroom/republican-news/",
                "https://www.indian.senate.gov/newsroom/democratic-news/",
            ],
        )
        self.assertEqual([item["tag"] for item in result["articles"]], ["majority", "minority"])


if __name__ == "__main__":
    unittest.main()
