from bs4 import BeautifulSoup
from datetime import datetime
from sources.fetching import fetch_page_html

def fetch_crs_articles(start_date=None):
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
