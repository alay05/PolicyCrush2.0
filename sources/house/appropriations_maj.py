from sources.house.common import get_house_page
from bs4 import BeautifulSoup
from datetime import datetime

def fetch_appr_maj_articles(start_date=None):
    results = []
    url = "https://appropriations.house.gov/news/press-releases"

    response = get_house_page(url, start_date=start_date)

    if response.status_code != 200:
        return results

    soup = BeautifulSoup(response.text, "html.parser")
    articles = soup.select("div.views-row")

    for article in articles:
        try:
            # Title and relative URL
            title_tag = article.select_one("div.h3 a")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "").strip()
            full_url = "https://appropriations.house.gov" + href

            # Date
            date_divs = article.select("div.row div.col-auto")
            if not date_divs:
                continue
            raw_date = date_divs[0].get_text(strip=True)
            pub_date = datetime.strptime(raw_date, "%B %d, %Y")

            if start_date and pub_date.date() < start_date:
                continue

            results.append({
                "title": title,
                "url": full_url,
                "date": pub_date.strftime("%Y-%m-%d")
            })
        except Exception:
            continue

    return results
