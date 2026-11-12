from sources.house.common import get_house_page
from bs4 import BeautifulSoup
from datetime import datetime

def fetch_vet_min_articles(start_date=None):
    results = []
    url = "https://democrats-veterans.house.gov/news/press-releases/table"

    response = get_house_page(url, start_date=start_date)

    if response.status_code != 200:
        return results

    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.select("table#browser_table tr")

    for row in rows:
        try:
            date_tag = row.select_one("td.date time")
            title_tag = row.select_one("td a")

            if not date_tag or not title_tag:
                continue

            pub_date = datetime.strptime(date_tag["datetime"], "%Y-%m-%d")
            if start_date and pub_date.date() < start_date:
                continue

            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "").strip()
            full_url = href if href.startswith("http") else "https://democrats-veterans.house.gov" + href

            results.append({
                "title": title,
                "url": full_url,
                "date": pub_date.strftime("%Y-%m-%d")
            })
        except Exception:
            continue

    return results
