from bs4 import BeautifulSoup
from datetime import datetime
import re

from sources.fetching import fetch_page_html


DATE_PATTERN = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")


def fetch_cms_inov_articles(start_date=None):
    url = "https://www.cms.gov/priorities/innovation/about/innovation-insights"
    html = fetch_page_html(url, wait_for_selector="h1", timeout_seconds=100)
    soup = BeautifulSoup(html, "html.parser")

    start_heading = soup.find(["h1", "h2"], string=lambda text: text and "Innovation Insights" in text)
    if not start_heading:
        raise ValueError("CMS Innovation page did not include the Innovation Insights section")

    results = []
    parseable_entries = 0

    for heading in start_heading.find_all_next("h3"):
        try:
            title = heading.get_text(" ", strip=True)
            if not title or title == "section title h3":
                continue

            info_nodes = []
            for sibling in heading.next_siblings:
                if getattr(sibling, "name", None) == "h3":
                    break
                info_nodes.append(sibling)

            date_text = None
            more_href = None
            for node in info_nodes:
                if isinstance(node, str):
                    text = node.strip()
                    if DATE_PATTERN.match(text):
                        date_text = text
                else:
                    text = node.get_text(" ", strip=True)
                    if not date_text and DATE_PATTERN.match(text):
                        date_text = text
                    if not more_href:
                        more_link = node.find("a", string=lambda text: text and text.strip() == "More")
                        if more_link and more_link.get("href"):
                            more_href = more_link["href"].strip()

            if not date_text:
                continue

            pub_date = datetime.strptime(date_text, "%B %d, %Y")
            parseable_entries += 1
            if start_date and pub_date.date() < start_date:
                continue

            article_url = more_href or ""
            if article_url and not article_url.startswith("http"):
                article_url = "https://www.cms.gov" + article_url

            results.append({
                "title": title,
                "url": article_url or url,
                "date": pub_date.strftime("%Y-%m-%d"),
            })

        except Exception:
            continue

        if len(results) >= 25:
            break

    return {
        "url": url,
        "articles": results,
    }
