import unittest
from datetime import date
from unittest.mock import Mock, patch

import requests

from sources.house.education_and_workforce_maj import fetch_eaw_maj_articles
from sources.house.common import get_house_page
from sources.house.oversight_min import fetch_ovs_min_articles


def requests_response(url, html):
    response = requests.Response()
    response.status_code = 200
    response.url = url
    response.encoding = "utf-8"
    response._content = html.encode("utf-8")
    return response


class HousePressSourceTests(unittest.TestCase):
    @patch("sources.house.common.fetch_response")
    def test_shared_loader_follows_pagination_through_start_date(self, fetch):
        fetch.side_effect = [
            requests_response(
                "https://committee.house.gov/news",
                '<time datetime="2026-02-02"></time><a rel="next" href="?page=1">Next</a>',
            ),
            requests_response(
                "https://committee.house.gov/news?page=1",
                '<time datetime="2025-12-20"></time><a rel="next" href="?page=2">Next</a>',
            ),
        ]

        result = get_house_page(
            "https://committee.house.gov/news",
            start_date=date(2026, 1, 1),
        )

        self.assertEqual(fetch.call_count, 2)
        self.assertIn("2026-02-02", result.text)
        self.assertIn("2025-12-20", result.text)

    @patch("sources.house.education_and_workforce_maj.get_house_page")
    def test_education_majority_resolves_relative_news_link_once(self, get):
        response = Mock(status_code=200)
        response.text = """
        <article class="newsblocker">
          <h2 class="newsie-titler"><a href="news/documentsingle.aspx?DocumentID=1">A release</a></h2>
          <time>November 8, 2026</time>
        </article>
        """
        get.return_value = response

        articles = fetch_eaw_maj_articles(date(2026, 11, 1))

        self.assertEqual(
            articles[0]["url"],
            "https://edworkforce.house.gov/news/documentsingle.aspx?DocumentID=1",
        )

    @patch("sources.house.oversight_min.get_house_page")
    def test_oversight_minority_reads_current_release_table(self, get):
        response = Mock(status_code=200)
        response.text = """
        <table id="browser_table"><tr>
          <td class="date"><time datetime="2026-11-06">11/06/26</time></td>
          <td headers="news-title"><a href=" /news/press-releases/a-release ">A release</a></td>
        </tr></table>
        """
        get.return_value = response

        articles = fetch_ovs_min_articles(date(2026, 11, 1))

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["date"], "2026-11-06")
        self.assertEqual(
            articles[0]["url"],
            "https://oversightdemocrats.house.gov/news/press-releases/a-release",
        )


if __name__ == "__main__":
    unittest.main()
