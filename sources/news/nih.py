import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from sources.fetching import fetch_page_html


NIH_NEWS_URL = "https://www.nih.gov/news-events/news-releases"
ARTICLE_SELECTOR = (
    "a.thumbnail-teaser__link[href*='/news-events/news-releases/']"
)
DATE_PATTERN = re.compile(r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})")


def _parse_nih_page(html, start_date=None):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(ARTICLE_SELECTOR)
    if not cards:
        raise ValueError("NIH news page did not include the expected release cards")

    results = []
    seen = set()

    for card in cards:
        title_tag = card.select_one(".thumbnail-teaser__heading")
        description_tag = card.select_one(".thumbnail-teaser__description")
        href = (card.get("href") or "").strip()
        if not title_tag or not description_tag or not href:
            continue

        date_match = DATE_PATTERN.search(description_tag.get_text(" ", strip=True))
        if not date_match:
            continue

        try:
            pub_date = datetime.strptime(date_match.group(1), "%B %d, %Y").date()
        except ValueError:
            continue

        if start_date and pub_date < start_date:
            continue

        title = title_tag.get_text(" ", strip=True)
        article_url = urljoin(NIH_NEWS_URL, href)
        if not title or article_url in seen:
            continue
        seen.add(article_url)

        results.append(
            {
                "title": title,
                "url": article_url,
                "date": pub_date.isoformat(),
            }
        )

    return results


def fetch_nih_articles(start_date=None):
    html = fetch_page_html(
        NIH_NEWS_URL,
        wait_for_selector=ARTICLE_SELECTOR,
        timeout_seconds=30,
    )
    return {
        "url": NIH_NEWS_URL,
        "articles": _parse_nih_page(html, start_date=start_date),
    }
