import re
from datetime import datetime

from bs4 import BeautifulSoup

from sources.senate.common import absolute_url, get_senate_page, parse_datetime, parse_listing_items

def fetch_home_articles(start_date=None):
    base_url = "https://www.hsgac.senate.gov"
    results = []

    def parse_news(url, tag):
        response = get_senate_page(url, start_date=start_date)
        if response.status_code != 200:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        blocks = soup.select("div.jet-listing-grid__item")
        items = []
        listing_year = datetime.now().year
        previous_month = None

        for block in blocks:
            # URL
            link_tag = block.select_one("a.jet-engine-listing-overlay-link")
            url = absolute_url(base_url, link_tag.get("href")) if link_tag else ""
            if not url:
                continue

            # Title
            title_tag = block.select_one("h5.jet-listing-dynamic-field__content")
            title = title_tag.get_text(strip=True).replace("➞", "").strip() if title_tag else None
            if not title:
                continue

            # Date
            month_tag = block.select_one("div.sen-listing-month time")
            day_tag = block.select_one("div.sen-listing-day time")
            if not month_tag or not day_tag:
                continue

            try:
                month_text = month_tag.get_text(strip=True)
                day_text = day_tag.get_text(strip=True)
                month_number = datetime.strptime(month_text, "%b").month

                explicit_date = month_tag.get("datetime") or day_tag.get("datetime")
                if explicit_date and re.search(r"\b\d{4}\b", str(explicit_date)):
                    try:
                        parsed_date = parse_datetime(explicit_date)
                    except ValueError:
                        parsed_date = None
                    if parsed_date and parsed_date.year > 1900:
                        pub_date = parsed_date
                        previous_month = pub_date.month
                        listing_year = pub_date.year
                    else:
                        pub_date = None
                else:
                    pub_date = None

                # Listing cards expose month/day only. The feed is newest-to-oldest,
                # so if the month increases (Jan -> Dec) we've crossed into the prior year.
                if pub_date is None:
                    if previous_month is None and month_number - datetime.now().month > 6:
                        listing_year -= 1
                    elif previous_month is not None and month_number > previous_month:
                        listing_year -= 1

                    raw_date = f"{month_text} {day_text} {listing_year}"
                    pub_date = parse_datetime(raw_date, "%b %d %Y", "%B %d %Y")
                    previous_month = month_number
            except (TypeError, ValueError):
                continue

            if start_date and pub_date.date() < start_date:
                continue

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
            row_selectors=("div.jet-listing-grid__item", "article"),
            link_selectors=("a.jet-engine-listing-overlay-link", "h2 a[href]", "h3 a[href]", "a[href]"),
            date_selectors=("[class*='date']", "[class*='month']"),
        )

    results += parse_news("https://www.hsgac.senate.gov/media/majority-news/", "majority")
    results += parse_news("https://www.hsgac.senate.gov/media/minority-news/", "minority")

    return {
        "base_url": base_url,
        "articles": results,
    }
