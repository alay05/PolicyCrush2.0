import unittest
from datetime import date
from unittest.mock import patch

from sources.news.nih import NIH_NEWS_URL, _parse_nih_page, fetch_nih_articles


NIH_PAGE_HTML = """
<main>
  <ul>
    <li class="thumbnail-teaser">
      <a class="thumbnail-teaser__link link--no-tag"
         href="/news-events/news-releases/new-treatment-study">
        <div class="thumbnail-teaser__body">
          <h3 class="thumbnail-teaser__heading">New treatment study</h3>
          <p class="thumbnail-teaser__description">
            October 20, 2026 — NIH-funded researchers report new findings.
          </p>
        </div>
      </a>
    </li>
    <li class="thumbnail-teaser">
      <a class="thumbnail-teaser__link link--no-tag"
         href="/news-events/news-releases/older-study">
        <div class="thumbnail-teaser__body">
          <h3 class="thumbnail-teaser__heading">Older study</h3>
          <p class="thumbnail-teaser__description">
            October 10, 2026 — An older release.
          </p>
        </div>
      </a>
    </li>
  </ul>
</main>
"""


class NihNewsTests(unittest.TestCase):
    def test_parser_returns_release_cards_on_or_after_start_date(self):
        articles = _parse_nih_page(NIH_PAGE_HTML, start_date=date(2026, 10, 15))

        self.assertEqual(
            articles,
            [
                {
                    "title": "New treatment study",
                    "url": f"{NIH_NEWS_URL}/new-treatment-study",
                    "date": "2026-10-20",
                }
            ],
        )

    def test_fetch_uses_browser_backed_loader_and_standard_payload(self):
        with patch("sources.news.nih.fetch_page_html", return_value=NIH_PAGE_HTML) as fetch:
            payload = fetch_nih_articles(date(2026, 10, 1))

        fetch.assert_called_once_with(
            NIH_NEWS_URL,
            wait_for_selector=(
                "a.thumbnail-teaser__link[href*='/news-events/news-releases/']"
            ),
            timeout_seconds=30,
        )
        self.assertEqual(payload["url"], NIH_NEWS_URL)
        self.assertEqual(len(payload["articles"]), 2)

    def test_parser_rejects_block_or_changed_markup(self):
        with self.assertRaisesRegex(ValueError, "expected release cards"):
            _parse_nih_page("<html><title>Attention Required!</title></html>")


if __name__ == "__main__":
    unittest.main()
