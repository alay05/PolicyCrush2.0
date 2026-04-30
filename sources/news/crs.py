from bs4 import BeautifulSoup
from datetime import datetime

from config import Config
from sources.fetching import fetch_html
from sources.fetching import fetch_page_html


def fetch_crs_articles_from_api(start_date=None):
    api_key = Config.CONGRESS_API_KEY
    if not api_key:
        raise ValueError("CONGRESS_API_KEY is not configured")

    url = "https://api.congress.gov/v3/crsreport"
    response = fetch_html(
        f"{url}?format=json&limit=250&api_key={api_key}",
        timeout=30,
    )
    payload = __import__("json").loads(response)
    reports = payload.get("CRSReports", [])

    results = []
    for report in reports:
        try:
            publish_date = datetime.fromisoformat(report["publishDate"].replace("Z", "+00:00"))
        except Exception:
            continue

        if start_date and publish_date.date() < start_date:
            continue

        results.append(
            {
                "title": report.get("title", "").strip(),
                "url": f"https://www.congress.gov/crs-product/{report.get('id', '').strip()}",
                "date": publish_date.strftime("%Y-%m-%d"),
            }
        )

    return {
        "url": "https://www.congress.gov/crs-products",
        "articles": results,
    }


def fetch_crs_articles(start_date=None):
    if Config.CONGRESS_API_KEY:
        return fetch_crs_articles_from_api(start_date)

    url = "https://www.congress.gov/crs-products"
    html = fetch_page_html(url, wait_for_selector="div.column-equal", timeout_seconds=10)
    soup = BeautifulSoup(html, "html.parser")

    containers = soup.select("div.column-equal")

    # Look for the one containing the 'Recent' header
    recent_div = None
    for div in containers:
        if div.find("h2") and div.find("h2").text.strip() == "Recent":
            recent_div = div
            break

    if not recent_div:
        heading = soup.find(["h2", "h3"], string=lambda text: text and text.strip() == "Recent")
        recent_div = heading.parent if heading else None

    if not recent_div:
        raise ValueError("Could not locate CRS recent section")

    p_tags = recent_div.find_all("p")

    results = []

    for p in p_tags:
        try:
            link = p.find("a")
            title = p.find("strong")
            parts = list(p.stripped_strings)

            if not link or not title or len(parts) < 2:
                continue

            date_text = parts[-1].strip()
            pub_date = datetime.strptime(date_text, "%B %d, %Y")
            if start_date and pub_date.date() < start_date:
                continue

            results.append({
                "title": title.text.strip(),
                "url": "https://www.congress.gov" + link["href"],
                "date": pub_date.strftime("%Y-%m-%d")
            })

        except Exception:
            continue

    return {
        "url": url,
        "articles": results,
    }
