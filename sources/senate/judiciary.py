from bs4 import BeautifulSoup

from sources.senate.common import absolute_url, get_senate_page, parse_datetime, parse_listing_items

def fetch_jud_articles(start_date=None):
    base_url = "https://www.judiciary.senate.gov"
    results = []

    def parse_news(url, tag):
        response = get_senate_page(url, start_date=start_date)
        if response.status_code != 200:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        items = []

        for li in soup.select("li.PageList__item"):
            date_tag = li.select_one("p.Heading--time")
            link_tag = li.select_one("a.ArticleBlockLink")
            title_tag = link_tag.select_one("h2") if link_tag else None

            if not date_tag or not link_tag or not title_tag:
                continue

            try:
                pub_date = parse_datetime(date_tag.get_text(strip=True), "%m.%d.%Y")
            except (TypeError, ValueError):
                continue

            if start_date and pub_date.date() < start_date:
                continue

            url = absolute_url(base_url, link_tag.get("href"))

            items.append({
                "title": title_tag.get_text(strip=True),
                "url": url,
                "date": pub_date.date() if pub_date.time().isoformat() == "00:00:00" else pub_date,
                "tag": tag,
            })

        return items or parse_listing_items(
            soup,
            base_url=base_url,
            tag=tag,
            start_date=start_date,
            row_selectors=("li.PageList__item", "div.PressBrowser__itemRow", "article"),
            link_selectors=("a.ArticleBlockLink", "h2 a[href]", "h3 a[href]", "a[href]"),
            date_selectors=("p.Heading--time", "[class*='date']"),
            href_fragments=("/press/rep/releases/", "/press/dem/releases/"),
        )

    results += parse_news("https://www.judiciary.senate.gov/press/majority?expanded=true", "majority")
    results += parse_news("https://www.judiciary.senate.gov/press/minority?expanded=true", "minority")

    return {
        "base_url": base_url,
        "articles": results,
    }
