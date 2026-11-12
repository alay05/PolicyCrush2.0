from sources.house.common import get_house_page
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin

def fetch_eaw_maj_articles(start_date=None):
    results = []
    url = "https://edworkforce.house.gov/news"

    response = get_house_page(url, start_date=start_date)

    if response.status_code != 200:
        return results

    soup = BeautifulSoup(response.text, "html.parser")
    items = soup.select("article.newsblocker")

    for item in items:
        try:
            # Title and URL
            title_tag = item.select_one("h2.newsie-titler a")
            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")
            full_url = urljoin("https://edworkforce.house.gov/", href)

            # Date
            date_tag = item.select_one("time")
            pub_date = datetime.strptime(date_tag.get_text(strip=True), "%B %d, %Y")
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
