import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dateutil import parser

from sources.fetching import ScraperUnavailableError, fetch_response


REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 20


def get_senate_page(url, *, start_date=None, max_pages=8):
    """Fetch a Senate listing and include older pages through ``start_date``."""
    try:
        response = fetch_response(
            url,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxy_on_block=True,
        )
    except (ScraperUnavailableError, requests.RequestException) as error:
        print(f"Error loading Senate source {url}: {error}")
        response = requests.Response()
        response.status_code = 503
        response.url = url
        return response
    if response.status_code != 200:
        print(f"Error loading Senate source {url}: HTTP {response.status_code}")
        return response
    if not start_date:
        return response

    pages = [response.text]
    visited = {response.url}
    current_response = response
    for _ in range(max_pages - 1):
        soup = BeautifulSoup(current_response.text, "html.parser")
        page_dates = _dates_in_page(soup)
        if page_dates and min(value.date() for value in page_dates) < start_date:
            break

        next_link = soup.select_one("a[rel='next'][href]")
        if next_link is None:
            next_link = next(
                (
                    link
                    for link in soup.select("a[href]")
                    if " ".join(link.get_text(" ", strip=True).split()).lower() == "next"
                ),
                None,
            )
        next_url = (
            absolute_url(current_response.url, next_link.get("href"))
            if next_link
            else ""
        )
        if not next_url or next_url in visited:
            break

        try:
            current_response = fetch_response(
                next_url,
                headers=REQUEST_HEADERS,
                timeout=REQUEST_TIMEOUT,
                proxy_on_block=True,
            )
        except (ScraperUnavailableError, requests.RequestException) as error:
            print(f"Error loading Senate source page {next_url}: {error}")
            break
        if current_response.status_code != 200:
            print(
                f"Error loading Senate source page {next_url}: "
                f"HTTP {current_response.status_code}"
            )
            break
        visited.add(next_url)
        pages.append(current_response.text)

    response._content = "\n".join(pages).encode(response.encoding or "utf-8")
    return response


def absolute_url(base_url, href):
    href = str(href or "").strip()
    return urljoin(base_url, href) if href else ""


def parse_datetime(value, *formats):
    """Parse the date formats currently used across Senate committee sites."""
    text = " ".join(str(value or "").replace("\xa0", " ").split())
    if not text:
        raise ValueError("Missing date")

    for date_format in formats:
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            pass

    try:
        return parser.isoparse(text)
    except ValueError:
        return parser.parse(text, fuzzy=False)


DATE_PATTERNS = (
    re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},\s+\d{4}"
        r"(?:\s+(?:at\s+)?\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?))?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}"
        r"(?:\s+(?:at\s+)?\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?))?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d{4}-\d{2}-\d{2}"
        r"(?:[T\s]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?\b"
    ),
)


def _dates_in_page(soup):
    candidates = []
    for element in soup.select("time[datetime], time, [class*='date']"):
        value = element.get("datetime") or element.get_text(" ", strip=True)
        if value:
            candidates.append(value)
    text = soup.get_text(" ", strip=True)
    for pattern in DATE_PATTERNS:
        candidates.extend(match.group(0) for match in pattern.finditer(text))

    values = []
    for candidate in candidates:
        try:
            values.append(parser.parse(str(candidate), fuzzy=True))
        except (TypeError, ValueError, OverflowError):
            continue
    return values


def _record_datetime(record, date_selectors=()):
    """Extract a date from the current and legacy Senate site templates."""
    candidates = []
    selectors = ["time[datetime]", "time", "meta[itemprop='datePublished']"]
    selectors.extend(date_selectors)
    for selector in selectors:
        for element in record.select(selector):
            value = (
                element.get("datetime")
                or element.get("content")
                or element.get_text(" ", strip=True)
            )
            if value:
                candidates.append(value)

    text = record.get_text(" ", strip=True)
    for pattern in DATE_PATTERNS:
        candidates.extend(match.group(0) for match in pattern.finditer(text))

    for candidate in candidates:
        normalized = re.sub(r"\s+at\s+", " ", str(candidate), flags=re.IGNORECASE)
        normalized = normalized.replace("a.m.", "AM").replace("p.m.", "PM")
        try:
            return parser.parse(normalized, fuzzy=True)
        except (TypeError, ValueError, OverflowError):
            continue
    return None


def parse_listing_items(
    soup,
    *,
    base_url,
    tag,
    start_date=None,
    row_selectors=(),
    link_selectors=("a[href]",),
    date_selectors=(),
    href_fragments=(),
):
    """Parse dated cards/rows while tolerating Senate template redesigns."""
    rows = []
    for selector in row_selectors:
        rows.extend(soup.select(selector))

    if href_fragments:
        for link in soup.select("a[href]"):
            href = str(link.get("href") or "").lower()
            if not any(fragment.lower() in href for fragment in href_fragments):
                continue
            record = link
            for parent in link.parents:
                if getattr(parent, "name", None) in {"body", "html"}:
                    break
                if _record_datetime(parent, date_selectors):
                    record = parent
                    break
            rows.append(record)

    items = []
    seen_urls = set()
    for row in rows:
        link = None
        for selector in link_selectors:
            candidates = row.select(selector)
            if href_fragments:
                candidates = [
                    candidate
                    for candidate in candidates
                    if any(
                        fragment.lower() in str(candidate.get("href") or "").lower()
                        for fragment in href_fragments
                    )
                ]
            if candidates:
                link = candidates[0]
                break
        if not link:
            continue

        item_url = absolute_url(base_url, link.get("href"))
        title = " ".join(link.get_text(" ", strip=True).split())
        item_date = _record_datetime(row, date_selectors)
        if not item_url or not title or not item_date or item_url in seen_urls:
            continue
        if start_date and item_date.date() < start_date:
            continue

        seen_urls.add(item_url)
        items.append(
            {
                "title": title,
                "url": item_url,
                "date": (
                    item_date.date()
                    if item_date.time().isoformat() == "00:00:00"
                    else item_date
                ),
                "tag": tag,
            }
        )
    return items
