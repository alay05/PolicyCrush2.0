from sources.house.common import get_house_page
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin

def fetch_ovs_min_articles(start_date=None):
    results = []
    base_url = "https://oversightdemocrats.house.gov"
    url = f"{base_url}/news/press-releases"

    response = get_house_page(url, start_date=start_date)
    if response.status_code != 200:
        return results

    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.select("table#browser_table tr")

    for row in rows:
        try:
            title_tag = row.select_one("td[headers='news-title'] a")
            date_tag = row.select_one("td.date time[datetime]")
            if not title_tag or not date_tag:
                continue

            title = title_tag.get_text(strip=True)
            url = urljoin(base_url, title_tag["href"].strip())
            pub_date = datetime.strptime(date_tag["datetime"], "%Y-%m-%d")

            if start_date and pub_date.date() < start_date:
                continue

            results.append({
                "title": title,
                "url": url,
                "date": pub_date.strftime("%Y-%m-%d")
            })
        except Exception:
            continue

    return results
