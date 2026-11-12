from bs4 import BeautifulSoup

from sources.senate.common import absolute_url, get_senate_page, parse_datetime, parse_listing_items

def fetch_appr_articles(start_date=None):
    base_url = "https://www.appropriations.senate.gov"
    results = []

    def parse_news(url, tag):
        response = get_senate_page(url, start_date=start_date)
        if response.status_code != 200:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.select("table.table tbody tr")
        items = []

        for row in rows:
            date_tag = row.select_one("td.date time")
            link_tag = row.select_one("td a")

            if not date_tag or not link_tag:
                continue

            try:
                pub_date = parse_datetime(
                    date_tag.get("datetime") or date_tag.get_text(strip=True),
                    "%Y-%m-%d",
                )
            except (TypeError, ValueError):
                continue

            if start_date and pub_date.date() < start_date:
                continue

            title = link_tag.get_text(strip=True)
            url = absolute_url(base_url, link_tag.get("href"))

            items.append({
                "title": title,
                "url": url,
                "date": pub_date.date() if pub_date.time().isoformat() == "00:00:00" else pub_date,
                "tag": tag,
            })

        return items or parse_listing_items(
            soup,
            base_url=base_url,
            tag=tag,
            start_date=start_date,
            row_selectors=("table.table tbody tr", "div.PressBrowser__itemRow", "article"),
            link_selectors=("td a[href]", "h2 a[href]", "h3 a[href]", "a[href]"),
            date_selectors=("[class*='date']",),
            href_fragments=(f"/news/{tag}/",),
        )

    results += parse_news("https://www.appropriations.senate.gov/news/majority", "majority")
    results += parse_news("https://www.appropriations.senate.gov/news/minority", "minority")

    return {
        "base_url": base_url,
        "articles": results,
    }
