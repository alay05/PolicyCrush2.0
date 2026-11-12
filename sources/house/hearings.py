import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from dateutil import parser

from sources.congress_meetings import fetch_committee_hearings
from sources.fetching import fetch_response


CALENDAR_URL = "https://docs.house.gov/Committee/Calendar/ByWeek.aspx"
EVENT_URL = "https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID={}"
EASTERN = ZoneInfo("America/New_York")
HOUSE_COMMITTEES = (
    "Appropriations",
    "Budget",
    "Education and Workforce",
    "Energy and Commerce (E&C)",
    "Homeland Security",
    "Joint Economic",
    "Judiciary",
    "Natural Resources",
    "Oversight",
    "Rules",
    "Small Business",
    "Veterans Affairs",
    "Ways and Means",
)
COMMITTEE_MARKERS = {
    "Committee on Appropriations": "Appropriations",
    "Committee on the Budget": "Budget",
    "Committee on Education and Workforce": "Education and Workforce",
    "Committee on Energy and Commerce": "Energy and Commerce (E&C)",
    "Committee on Homeland Security": "Homeland Security",
    "Committee on the Judiciary": "Judiciary",
    "Committee on Natural Resources": "Natural Resources",
    "Committee on Oversight and Government Reform": "Oversight",
    "Committee on Oversight and Accountability": "Oversight",
    "Committee on Oversight and Reform": "Oversight",
    "Committee on Rules": "Rules",
    "Committee on Small Business": "Small Business",
    "Committee on Veterans' Affairs": "Veterans Affairs",
    "Committee on Veterans’ Affairs": "Veterans Affairs",
    "Committee on Ways and Means": "Ways and Means",
}
JOINT_ECONOMIC_BY_PREFIX = {
    "jsec": "Joint Economic",
    "jjec": "Joint Economic",
    "jhje": "Joint Economic",
}


def _week_starts(start_date, end_date):
    current = start_date - timedelta(days=(start_date.weekday() + 1) % 7)
    final = end_date - timedelta(days=(end_date.weekday() + 1) % 7)
    while current <= final:
        yield current
        current += timedelta(days=7)


def _possible_tracked_committee(label):
    normalized = " ".join(str(label or "").split())
    return "subcommittee" in normalized.lower() or any(
        marker in normalized for marker in COMMITTEE_MARKERS
    )


@lru_cache(maxsize=180)
def _calendar_entries_for_week(week_start):
    week_end = week_start + timedelta(days=6)
    # fetch_response deliberately has a small interface. Add the House query to
    # the URL so both direct and optional proxy transports request the same page.
    calendar_url = f"{CALENDAR_URL}?WeekOf={week_start:%m%d%Y}_{week_end:%m%d%Y}"
    response = fetch_response(calendar_url, timeout=20, proxy_on_block=True)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    entries = []
    for cell in soup.select("table.weekly td"):
        day_link = cell.select_one("div.calendar-text a[title]")
        if not day_link:
            continue
        day_value = day_link.get("title")
        for paragraph in cell.select("p"):
            event_link = paragraph.select_one("a[href*='ByEvent.aspx?EventID=']")
            committee_tag = paragraph.select_one("span[title]")
            if not event_link or not committee_tag:
                continue
            committee_label = committee_tag.get("title") or committee_tag.get_text(
                " ", strip=True
            )
            if not _possible_tracked_committee(committee_label):
                continue
            event_match = re.search(
                r"EventID=(\d+)",
                event_link.get("href", ""),
                re.IGNORECASE,
            )
            time_match = re.search(
                r"\b\d{1,2}:\d{2}\s*(?:AM|PM)\b",
                paragraph.get_text(" ", strip=True),
                re.IGNORECASE,
            )
            if not event_match or not time_match:
                continue
            try:
                event_date = parser.parse(f"{day_value} {time_match.group(0)}")
                event_date = event_date.replace(tzinfo=EASTERN)
            except (TypeError, ValueError, OverflowError):
                continue
            entries.append((event_match.group(1), event_date))
    return entries


def _committee_from_event_text(text):
    for marker, committee in COMMITTEE_MARKERS.items():
        if marker.lower() in text.lower():
            return committee
    return None


@lru_cache(maxsize=2048)
def _fetch_event(event_id, event_date):
    url = EVENT_URL.format(event_id)
    response = fetch_response(url, timeout=20, proxy_on_block=True)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    heading = next(
        (
            tag
            for tag in soup.select("h1, h2, h3")
            if tag.get_text(" ", strip=True).lower().startswith("hearing:")
        ),
        None,
    )
    if not heading:
        return None
    title = heading.get_text(" ", strip=True).split(":", 1)[1].strip().strip('"')
    text = soup.get_text(" ", strip=True)
    committee = _committee_from_event_text(text)
    if not title or not committee:
        return None
    return committee, {
        "title": title,
        "url": url,
        "date": event_date,
        "tag": "hearing",
    }


def _fetch_house_calendar(start_date, today):
    calendar_end = max(start_date, today + timedelta(days=45))
    entries = {}
    week_starts = list(_week_starts(start_date, calendar_end))
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(_calendar_entries_for_week, week_start): week_start
            for week_start in week_starts
        }
        for future in as_completed(futures):
            try:
                for event_id, event_date in future.result():
                    if event_date.date() >= start_date:
                        entries[event_id] = event_date
            except Exception as error:
                print(f"Error loading House calendar week {futures[future]}: {error}")

    grouped = {committee: [] for committee in HOUSE_COMMITTEES}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(_fetch_event, event_id, event_date): event_id
            for event_id, event_date in entries.items()
        }
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as error:
                print(f"Error loading House calendar event {futures[future]}: {error}")
                continue
            if result:
                committee, hearing = result
                grouped[committee].append(hearing)

    for hearings in grouped.values():
        hearings.sort(key=lambda item: item["date"], reverse=True)
    return grouped


def fetch_house_hearings(start_date=None, *, today=None):
    """Return official House calendar hearings for existing committees."""
    today = today or date.today()
    start_date = start_date or today
    if isinstance(start_date, datetime):
        start_date = start_date.date()

    grouped = _fetch_house_calendar(start_date, today)
    # Joint Economic meetings are published in Congress.gov's joint calendar,
    # not consistently in the House Committee Repository.
    joint = fetch_committee_hearings(
        "joint",
        JOINT_ECONOMIC_BY_PREFIX,
        start_date,
        today=today,
    )
    grouped["Joint Economic"] = joint["Joint Economic"]
    return grouped
