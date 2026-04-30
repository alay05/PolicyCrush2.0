from bs4 import BeautifulSoup
from datetime import datetime
from sources.fetching import fetch_page_html

def fetch_congress_articles(start_date=None):
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
