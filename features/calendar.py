"""Import official congressional event links into the AddEvent calendar."""
import os
import re
from datetime import datetime, timedelta
from html import escape, unescape
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from features.calendar_pull import API_BASE, DEFAULT_CALENDAR_KEY, _api_session, resolve_calendar_id
from sources.congress_meetings import CongressApiError, _fetch_detail
from sources.fetching import fetch_response

EASTERN = ZoneInfo("America/New_York")


class EventImportError(ValueError):
    """A safe, actionable message to display on the import form."""


def _event_source(url):
    try:
        parts = urlsplit(url.strip())
        if parts.scheme not in {"https", "http"} or parts.username or parts.password or parts.port:
            raise ValueError
        host = (parts.hostname or "").lower()
        match = re.fullmatch(
            r"/event/(\d+)(?:th|st|nd|rd)-congress/(senate|house|joint)-event/(\d+)/?",
            parts.path, re.IGNORECASE,
        )
        if host in {"congress.gov", "www.congress.gov"} and match:
            congress, chamber, event_id = match.groups()
            chamber = chamber.lower()
            canonical = f"https://www.congress.gov/event/{congress}th-congress/{chamber}-event/{event_id}"
            return canonical, (int(congress), chamber, event_id)
        if host == "docs.house.gov" and parts.path.lower() == "/committee/calendar/byevent.aspx":
            query = {key.lower(): value for key, value in parse_qs(parts.query).items()}
            ids = query.get("eventid", [])
            if len(ids) == 1 and re.fullmatch(r"\d+", ids[0]):
                return f"https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID={ids[0]}", None
    except ValueError:
        pass
    raise EventImportError("Paste a Congress.gov event link or a docs.house.gov committee event link from the Senate or House tool.")


def _house_event(html):
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("#previewPanel h1")
    when = soup.select_one("#previewPanel .meetingTime")
    location = soup.select_one("#previewPanel .location")
    if not heading or not when:
        raise EventImportError("The House page does not contain a scheduled event with a date and time.")
    for small in heading.select("small"):
        small.decompose()
    title = re.sub(r"^Hearing:\s*", "", heading.get_text(" ", strip=True), flags=re.I).strip('"“” ')
    when_text = " ".join(when.get_text(" ", strip=True).split())
    try:
        start = datetime.strptime(when_text, "%A, %B %d, %Y (%I:%M %p)").replace(tzinfo=EASTERN)
    except ValueError as exc:
        raise EventImportError("The House event has no definite scheduled time, or its date format was not recognized.") from exc
    return title, start, location.get_text(" ", strip=True) if location else ""


def event_from_url(url):
    """Read fresh source data, preserving the title and Eastern wall time."""
    canonical, meeting = _event_source(url)
    if meeting:
        try:
            detail = _fetch_detail(*meeting)
        except CongressApiError as exc:
            raise EventImportError(f"Could not load the Congress.gov event. {exc}") from exc
        status = str(detail.get("meetingStatus") or "").lower()
        if status and status not in {"scheduled", "completed"}:
            raise EventImportError(f"This event is marked {status}; it was not added to the calendar.")
        title = " ".join(str(detail.get("title") or "").split())
        try:
            date_text = detail.get("date") or ""
            if "T" not in date_text:
                raise ValueError
            start = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
            if start.tzinfo is None:
                raise ValueError
            start = start.astimezone(EASTERN)
        except (TypeError, ValueError) as exc:
            raise EventImportError("Congress.gov has not supplied a definite date and time for this event.") from exc
        location = detail.get("location") or ""
        if isinstance(location, dict):
            location = ", ".join(str(location[key]) for key in ("room", "building", "address") if location.get(key))
    else:
        try:
            response = fetch_response(canonical, timeout=20)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise EventImportError("Could not load the House event page. Please try again.") from exc
        title, start, location = _house_event(response.text)
    if not title:
        raise EventImportError("The event has no title and could not be added.")
    return {
        "title": title,
        "datetime_start": start.strftime("%Y-%m-%d %H:%M"),
        "datetime_end": (start + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
        "location": str(location),
        "description": canonical,
        "timezone": "America/New_York",
    }


def _parse_dt_minute(value):
    try:
        return datetime.fromisoformat(value).replace(second=0, microsecond=0, tzinfo=None)
    except (TypeError, ValueError):
        return None


def _same_source(description, source):
    # Read both plain URLs and hrefs from AddEvent's HTML descriptions.
    for candidate in re.findall(r'https?://[^\s<>"\']+', unescape(description or "")):
        try:
            if _event_source(candidate)[0] == source:
                return True
        except EventImportError:
            pass
    return False


def create_event_addevent(data, *, dedupe=True, dedupe_window_hours=3, calendar_id=None):
    """Create only on the configured calendar; stop if duplicate lookup fails."""
    try:
        session = _api_session()
    except RuntimeError as exc:
        raise EventImportError("AddEvent is not configured. Set ADDEVENT_API_KEY on the server.") from exc
    with session:
        target = calendar_id or os.getenv("ADDEVENT_CALENDAR_ID", "").strip()
        try:
            target = target or resolve_calendar_id(session, DEFAULT_CALENDAR_KEY)
        except requests.RequestException as exc:
            raise EventImportError("Could not look up the AddEvent calendar. Check the API key and try again.") from exc
        if not target:
            raise EventImportError("Could not find the AddEvent calendar. Check ADDEVENT_CALENDAR_KEY or set ADDEVENT_CALENDAR_ID.")
        payload = {**data, "calendar_id": str(target)}
        if dedupe:
            start = _parse_dt_minute(data.get("datetime_start"))
            if start is None:
                raise EventImportError("The event start time is invalid.")
            window = timedelta(hours=max(1, dedupe_window_hours))
            params = {
                "calendar_ids": str(target),
                "datetime_min": (start - window).strftime("%Y-%m-%d %H:%M:%S"),
                "datetime_max": (start + window).strftime("%Y-%m-%d %H:%M:%S"),
                "page_size": 20,
                "page": 1,
            }
            try:
                while True:
                    response = session.get(f"{API_BASE}/events", params=params, timeout=20)
                    response.raise_for_status()
                    events = response.json()["events"]
                    if not isinstance(events, list):
                        raise ValueError
                    for event in events:
                        event_start = _parse_dt_minute(event.get("datetime_start"))
                        if (str(event.get("calendar_id")) == str(target) and event_start
                                and abs(event_start - start) <= window
                                and _same_source(event.get("description"), data["description"])):
                            return {**event, "deduped": True}
                    if len(events) < 20:
                        break
                    params["page"] += 1
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                raise EventImportError("Could not check AddEvent for duplicates. Nothing was added; please try again.") from exc
        # AddEvent's rich-text description needs an explicit anchor to be clickable.
        # Keep the plain source in data for duplicate matching.
        source = escape(data["description"], quote=True)
        payload["description"] = f'<a href="{source}">{source}</a>'
        try:
            response = session.post(f"{API_BASE}/events", json=payload, timeout=20)
            response.raise_for_status()
            result = response.json()
            event = result.get("event", result)
            if not event.get("id"):
                raise ValueError
        except (requests.RequestException, ValueError, AttributeError) as exc:
            raise EventImportError("AddEvent did not confirm creation. Check the calendar before retrying.") from exc
        return {**event, "deduped": False}
