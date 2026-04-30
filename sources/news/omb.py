from bs4 import BeautifulSoup
from datetime import datetime
import re

from sources.fetching import fetch_page_html


DATE_PATTERN = re.compile(r"\d{2}/\d{2}/\d{4}")


def fetch_omb_articles(start_date=None):
    url = "https://www.reginfo.gov/public/do/eoAdvancedSearch"
    html = fetch_page_html(url, wait_for_selector="a[href*='eoDetails?rrid=']", timeout_seconds=100)
    soup = BeautifulSoup(html, "html.parser")
    detail_links = soup.select("a[href*='eoDetails?rrid=']")
    if not detail_links:
        raise ValueError("OMB search page did not include any EO detail links")

    results = []
    seen = set()
    parseable_entries = 0

    for detail_link in detail_links:
        try:
            row = detail_link.find_parent("tr")
            if not row:
                continue

            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            row_text = " ".join(cells)
            if "HHS/" not in row_text:
                continue

            date_match = DATE_PATTERN.search(row_text)
            if not date_match:
                continue

            pub_date = datetime.strptime(date_match.group(0), "%m/%d/%Y")
            parseable_entries += 1
            if start_date and pub_date.date() < start_date:
                continue

            detail_href = detail_link.get("href", "").strip()
            if not detail_href:
                continue
            article_url = detail_href if detail_href.startswith("http") else "https://www.reginfo.gov" + detail_href

            title = detail_link.get_text(" ", strip=True)
            if not title or title in seen:
                continue
            seen.add(title)

            results.append({
                "title": title,
                "url": article_url,
                "date": pub_date.strftime("%Y-%m-%d")
            })
        except Exception:
            continue

    if parseable_entries == 0:
        raise ValueError("OMB search page did not include any parseable HHS rulemaking entries")

    return {
        "url": url,
        "articles": results,
    }
