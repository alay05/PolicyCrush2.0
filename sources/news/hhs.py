from bs4 import BeautifulSoup
from datetime import datetime
import re

from sources.fetching import fetch_html, fetch_page_html, ScraperUnavailableError


DATE_PATTERN = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})\s+Press Release")
BLOCK_PATTERNS = ("Access Denied", "Request unsuccessful", "temporarily unavailable")
HHS_URLS = [
    "https://www.hhs.gov/news",
    "https://www.hhs.gov/press-room/index.html",
    "https://www.hhs.gov/about/news/index.html?p=0",
]


def _looks_blocked(html: str) -> bool:
    lowered = html.lower()
    return any(pattern.lower() in lowered for pattern in BLOCK_PATTERNS)


def _parse_hhs_page(html: str, page_url: str, start_date=None):
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup

    results = []
    seen = set()

    for item in main.select("li, article, div"):
        try:
            text_blob = item.get_text(" ", strip=True)
            if "Press Release" not in text_blob:
                continue

            date_match = DATE_PATTERN.search(text_blob)
            if not date_match:
                continue

            link_tag = item.select_one("a[href]")
            if not link_tag:
                continue

            href = (link_tag.get("href") or "").strip()
            title = link_tag.get_text(" ", strip=True)
            if not href or not title:
                continue

            if href.startswith("#") or "/archive" in href or "pagefreezer" in href or "archive-it" in href:
                continue

            pub_date = datetime.strptime(date_match.group(1), "%B %d, %Y")
            if start_date and pub_date.date() < start_date:
                continue

            full_url = href if href.startswith("http") else "https://www.hhs.gov" + href
            key = (title, full_url)
            if key in seen:
                continue
            seen.add(key)

            results.append({
                "title": title,
                "url": full_url,
                "date": pub_date.strftime("%Y-%m-%d"),
            })
        except Exception:
            continue

    return {
        "url": page_url,
        "articles": results,
    }


def fetch_hhs_articles(start_date=None):
    errors = []

    for url in HHS_URLS:
        try:
            try:
                html = fetch_html(url)
                if _looks_blocked(html):
                    raise ValueError("blocked response")
            except Exception:
                html = fetch_page_html(url, wait_for_selector="h1", timeout_seconds=20)
                if _looks_blocked(html):
                    raise ValueError("blocked response")

            parsed = _parse_hhs_page(html, url, start_date=start_date)
            return parsed
        except (ScraperUnavailableError, ValueError) as exc:
            errors.append(f"{url}: {exc}")
            continue

    raise ScraperUnavailableError(" ; ".join(errors) or "No accessible HHS news page found")
