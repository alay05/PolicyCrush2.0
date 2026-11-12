from bs4 import BeautifulSoup

from sources.senate.common import (
    absolute_url,
    get_senate_page,
    parse_datetime,
    parse_listing_items,
)

def fetch_budg_articles(start_date=None):
    base_url = "https://www.budget.senate.gov"
    results = []

    def parse_press(url, tag):
        response = get_senate_page(url, start_date=start_date)
        if response.status_code != 200:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.select("table#browser_table tr")
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
            row_selectors=("div.PressBrowser__itemRow", "article", "li.PageList__item"),
            link_selectors=("h2 a[href]", "h3 a[href]", "a[href]"),
            date_selectors=("[class*='date']",),
            href_fragments=("/newsroom/press/", "/newsroom/press-releases/"),
        )

    results += parse_press(
        "https://www.budget.senate.gov/chairman/newsroom/press/?press_type=press_release",
        "majority",
    )
    results += parse_press(
        "https://www.budget.senate.gov/ranking-member/newsroom/press/?press_type=press_release",
        "minority",
    )

    return {
        "base_url": base_url,
        "articles": results,
    }
