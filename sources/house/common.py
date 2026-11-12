from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dateutil import parser

from sources.fetching import ScraperUnavailableError, fetch_response


HOUSE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _page_dates(soup):
    values = []
    for element in soup.select("time[datetime], time, [class*='date']"):
        raw = element.get("datetime") or element.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            values.append(parser.parse(raw, fuzzy=True))
        except (TypeError, ValueError, OverflowError):
            continue
    return values


def _next_page_url(response_url, soup):
    link = soup.select_one(
        "a[rel='next'][href], li.pager__item--next a[href], "
        "li.pager-next a[href], a.next[href]"
    )
    if link is None:
        link = next(
            (
                candidate
                for candidate in soup.select("a[href]")
                if " ".join(candidate.get_text(" ", strip=True).split()).lower()
                in {"next", "next ›", "next »", "›", "»"}
            ),
            None,
        )
    return urljoin(response_url, link.get("href")) if link else ""


def get_house_page(url, *, start_date=None, max_pages=8):
    """Fetch and combine House listing pages through the requested date."""
    try:
        response = fetch_response(
            url,
            headers=HOUSE_HEADERS,
            timeout=30,
            proxy_on_block=True,
        )
    except (ScraperUnavailableError, requests.RequestException) as error:
        # Preserve the existing source contract: callers inspect status_code and
        # return an empty list rather than losing every other committee.
        print(f"Error loading House source {url}: {error}")
        response = requests.Response()
        response.status_code = 503
        response.url = url
        return response

    if response.status_code != 200 or not start_date:
        return response

    pages = [response.text]
    current = response
    visited = {url, response.url}
    for _ in range(max_pages - 1):
        soup = BeautifulSoup(current.text, "html.parser")
        dates = _page_dates(soup)
        if dates and min(value.date() for value in dates) < start_date:
            break

        next_url = _next_page_url(current.url, soup)
        if not next_url or next_url in visited:
            break
        try:
            current = fetch_response(
                next_url,
                headers=HOUSE_HEADERS,
                timeout=30,
                proxy_on_block=True,
            )
        except (ScraperUnavailableError, requests.RequestException) as error:
            print(f"Error loading House source page {next_url}: {error}")
            break
        if current.status_code != 200:
            print(
                f"Error loading House source page {next_url}: "
                f"HTTP {current.status_code}"
            )
            break
        visited.add(next_url)
        pages.append(current.text)

    response._content = "\n".join(pages).encode(response.encoding or "utf-8")
    return response
