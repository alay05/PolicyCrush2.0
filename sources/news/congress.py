from bs4 import BeautifulSoup
from datetime import datetime

from config import Config
from sources.fetching import fetch_html
from sources.fetching import fetch_page_html


def fetch_congress_articles_from_api(start_date=None):
    api_key = Config.CONGRESS_API_KEY
    if not api_key:
        raise ValueError("CONGRESS_API_KEY is not configured")

    url = "https://api.congress.gov/v3/bill"
    response = fetch_html(
        f"{url}?format=json&limit=250&sort=updateDate+desc&api_key={api_key}",
        timeout=30,
    )
    payload = __import__("json").loads(response)
    bills = payload.get("bills", [])

    results = []
    for bill in bills:
        latest_action = bill.get("latestAction") or {}
        action_date_text = latest_action.get("actionDate")
        if not action_date_text:
            continue

        try:
            pub_date = datetime.strptime(action_date_text, "%Y-%m-%d")
        except Exception:
            continue

        if start_date and pub_date.date() < start_date:
            continue

        congress = bill.get("congress")
        bill_type = (bill.get("type") or "").lower()
        number = bill.get("number")
        if not congress or not bill_type or not number:
            continue

        results.append(
            {
                "title": (bill.get("title") or "").strip(),
                "url": f"https://www.congress.gov/bill/{congress}th-congress/{bill_type.lower()}-bill/{number}",
                "date": pub_date.strftime("%Y-%m-%d"),
            }
        )

    return {
        "url": "https://www.congress.gov/search?q=%7B%22source%22%3A%22legislation%22%7D",
        "articles": results,
    }


def fetch_congress_articles(start_date=None):
    if Config.CONGRESS_API_KEY:
        return fetch_congress_articles_from_api(start_date)

    url = "https://www.congress.gov/search?q=%7B%22source%22%3A%22legislation%22%7D"
    html = fetch_page_html(url, wait_for_selector="li.expanded", timeout_seconds=100)
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("li.expanded")
    if not items:
        raise ValueError("Congress.gov search page did not include the expected result rows")

    results = []

    for item in items:
        title_tag = item.select_one("span.result-title")
        link_tag = item.select_one("span.result-heading a")
        latest_action_span = next(
            (span for span in item.select("span.result-item") if "Latest Action:" in span.text), None
        )

        if not title_tag or not link_tag or not latest_action_span:
            continue

        try:
            action_text = latest_action_span.text.strip()
            date_part = action_text.split(" - ")[-1].split()[0]
            pub_date = datetime.strptime(date_part, "%m/%d/%Y")
        except Exception:
            continue

        if start_date and pub_date.date() < start_date:
            continue

        results.append({
            "title": title_tag.text.strip(),
            "url": "https://www.congress.gov" + link_tag["href"],
            "date": pub_date.strftime("%Y-%m-%d")
        })

    return {
        "url": url,
        "articles": results
    }
