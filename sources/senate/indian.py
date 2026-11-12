from bs4 import BeautifulSoup

from sources.senate.common import (
    absolute_url,
    get_senate_page,
    parse_datetime,
    parse_listing_items,
)

def fetch_ind_articles(start_date=None):
    base_url = "https://www.indian.senate.gov"
    results = []

    def parse_section(url, tag):
        response = get_senate_page(url, start_date=start_date)
        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.select("div.jet-listing-grid__item")
        items = []

        for article in articles:
            date_tag = article.select_one("div.jet-listing-dynamic-field__content")
            title_tag = article.select_one("div.elementor-heading-title a")

            if not date_tag or not title_tag:
                continue

            try:
                pub_date = parse_datetime(
                    date_tag.get("datetime") or date_tag.get_text(strip=True),
                    "%B %d, %Y",
                    "%Y-%m-%d",
                )
            except (TypeError, ValueError):
                continue

            if start_date and pub_date.date() < start_date:
                continue

            title = title_tag.get_text(strip=True)
            url = absolute_url(base_url, title_tag.get("href"))

            items.append({
                "title": title,
                "url": url,
                "date": pub_date.date() if pub_date.time().isoformat() == "00:00:00" else pub_date,
                "tag": tag,
            })

        fragment = "/press-release/republican/" if tag == "majority" else "/press-release/democratic/"
        return items or parse_listing_items(
            soup,
            base_url=base_url,
            tag=tag,
            start_date=start_date,
            row_selectors=("div.jet-listing-grid__item", "article"),
            link_selectors=("div.elementor-heading-title a[href]", "h2 a[href]", "h3 a[href]", "a[href]"),
            date_selectors=("[class*='date']", ".jet-listing-dynamic-field__content"),
            href_fragments=(fragment,),
        )

    results += parse_section(base_url + "/newsroom/republican-news/", "majority")
    results += parse_section(base_url + "/newsroom/democratic-news/", "minority")

    return {
        "base_url": base_url,
        "articles": results,
    }
