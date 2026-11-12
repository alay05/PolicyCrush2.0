import asyncio
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dateutil import parser

from config import Config


API_ROOT = "https://api.congress.gov/v3"
CACHE_VERSION = 1
EASTERN = ZoneInfo("America/New_York")
_SYNC_LOCK = threading.Lock()


class CongressApiError(RuntimeError):
    pass


def _api_get(path, params=None):
    if not Config.CONGRESS_API_KEY:
        raise CongressApiError("CONGRESS_API_KEY is not configured")

    try:
        response = requests.get(
            f"{API_ROOT}/{path.lstrip('/')}",
            params={"format": "json", **(params or {})},
            headers={"X-Api-Key": Config.CONGRESS_API_KEY},
            timeout=Config.HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise CongressApiError("Congress.gov API request failed") from exc

    if response.status_code != 200:
        raise CongressApiError(
            f"Congress.gov API returned HTTP {response.status_code} for {path}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise CongressApiError("Congress.gov API returned invalid JSON") from exc


def _congress_for_date(value):
    value = value.date() if isinstance(value, datetime) else value
    effective_year = value.year
    if effective_year % 2 and value < date(effective_year, 1, 3):
        effective_year -= 1
    return ((effective_year - 1789) // 2) + 1


def _cache_path(congress, chamber):
    return Path(Config.CONGRESS_CACHE_DIR) / f"{congress}-{chamber}.json"


def _blob_path(congress, chamber):
    return f"scraper-cache/congress-meetings-{congress}-{chamber}.json"


async def _consume_async_stream(stream):
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return b"".join(chunks)


def _read_blob_bytes(result, token):
    stream = getattr(result, "stream", None)
    if stream:
        if hasattr(stream, "__aiter__"):
            return asyncio.run(_consume_async_stream(stream))
        return b"".join(stream)

    download_url = (
        getattr(result, "download_url", None)
        or getattr(result, "downloadUrl", None)
        or getattr(result, "url", None)
    )
    if not download_url:
        return b""
    response = requests.get(
        download_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=Config.HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.content


def _valid_cache(payload):
    return (
        isinstance(payload, dict)
        and payload.get("version") == CACHE_VERSION
        and isinstance(payload.get("records"), dict)
    )


def _load_cache(congress, chamber):
    blob_token = os.getenv("BLOB_READ_WRITE_TOKEN", "").strip()
    if blob_token:
        try:
            from vercel.blob import get as blob_get

            result = blob_get(
                _blob_path(congress, chamber),
                access="private",
                token=blob_token,
            )
            if result:
                raw = _read_blob_bytes(result, blob_token)
                payload = json.loads(raw.decode("utf-8"))
                if isinstance(payload, dict) and not _valid_cache(payload):
                    nested_url = (
                        payload.get("download_url")
                        or payload.get("downloadUrl")
                        or payload.get("url")
                    )
                    if nested_url:
                        nested = requests.get(
                            nested_url,
                            headers={"Authorization": f"Bearer {blob_token}"},
                            timeout=Config.HTTP_TIMEOUT_SECONDS,
                        )
                        nested.raise_for_status()
                        payload = nested.json()
                if _valid_cache(payload):
                    return payload
        except Exception as exc:
            print(f"Could not read Congress.gov meeting cache from Vercel Blob: {exc}")

    path = _cache_path(congress, chamber)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if _valid_cache(payload):
            return payload
    except (OSError, ValueError):
        pass
    return {"version": CACHE_VERSION, "synced_at": "", "records": {}}


def _save_cache(congress, chamber, payload):
    path = _cache_path(congress, chamber)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    temporary.write_bytes(encoded)
    temporary.replace(path)

    blob_token = os.getenv("BLOB_READ_WRITE_TOKEN", "").strip()
    if blob_token:
        try:
            from vercel.blob import put as blob_put

            blob_put(
                _blob_path(congress, chamber),
                encoded,
                access="private",
                content_type="application/json",
                overwrite=True,
                token=blob_token,
            )
        except Exception as exc:
            print(f"Could not write Congress.gov meeting cache to Vercel Blob: {exc}")


def _parse_utc(value):
    if not value:
        return None
    parsed = parser.isoparse(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cache_is_fresh(cache):
    try:
        synced_at = _parse_utc(cache.get("synced_at"))
    except (TypeError, ValueError):
        return False
    return bool(
        synced_at
        and datetime.now(timezone.utc) - synced_at
        < timedelta(seconds=Config.CONGRESS_CACHE_TTL_SECONDS)
    )


def _list_meetings(congress, chamber, since=None):
    items = []
    offset = 0
    while True:
        params = {"limit": 250, "offset": offset}
        if since:
            params["fromDateTime"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = _api_get(f"committee-meeting/{congress}/{chamber}", params)
        page = payload.get("committeeMeetings") or []
        items.extend(page)
        count = int((payload.get("pagination") or {}).get("count") or 0)
        offset += len(page)
        if not page or offset >= count:
            break
    return items


def _fetch_detail(congress, chamber, event_id):
    payload = _api_get(f"committee-meeting/{congress}/{chamber}/{event_id}")
    return payload.get("committeeMeeting") or {}


def _sync_meetings(congress, chamber, requested_coverage):
    with _SYNC_LOCK:
        cache = _load_cache(congress, chamber)
        try:
            cached_coverage = _parse_utc(cache.get("covered_from"))
        except (TypeError, ValueError):
            cached_coverage = None
        needs_expansion = not cached_coverage or requested_coverage < cached_coverage
        if _cache_is_fresh(cache) and not needs_expansion:
            return list(cache["records"].values())

        sync_started = datetime.now(timezone.utc)
        try:
            previous_sync = _parse_utc(cache.get("synced_at"))
        except (TypeError, ValueError):
            previous_sync = None
        # Expand backward when an older date is requested. Otherwise only read
        # updates since the last refresh. The overlap avoids losing an update at
        # the exact cache boundary.
        since = (
            requested_coverage
            if needs_expansion
            else previous_sync - timedelta(minutes=5)
            if previous_sync
            else requested_coverage
        )
        summaries = _list_meetings(congress, chamber, since=since)
        records = cache["records"]
        pending = []
        for summary in summaries:
            event_id = str(summary.get("eventId") or "")
            if not event_id:
                continue
            cached = records.get(event_id) or {}
            if (
                not cached.get("detail")
                or cached.get("updateDate") != summary.get("updateDate")
            ):
                pending.append((event_id, summary))

        failures = 0
        max_workers = max(1, min(Config.CONGRESS_API_MAX_WORKERS, 16))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_fetch_detail, congress, chamber, event_id): (
                    event_id,
                    summary,
                )
                for event_id, summary in pending
            }
            for future in as_completed(futures):
                event_id, summary = futures[future]
                try:
                    detail = future.result()
                except CongressApiError as exc:
                    failures += 1
                    print(f"Error loading Congress.gov meeting {event_id}: {exc}")
                    continue
                records[event_id] = {
                    "updateDate": summary.get("updateDate"),
                    "detail": detail,
                }

        if failures == 0:
            cache["synced_at"] = sync_started.isoformat()
            cache["covered_from"] = min(
                value for value in (cached_coverage, requested_coverage) if value
            ).isoformat()
        _save_cache(congress, chamber, cache)
        return list(records.values())


def fetch_committee_hearings(
    chamber,
    committee_by_prefix,
    start_date=None,
    *,
    today=None,
):
    """Return Congress.gov hearings grouped by the tool's committee names."""
    today = today or date.today()
    start_date = start_date or today
    if isinstance(start_date, datetime):
        start_date = start_date.date()

    grouped = {
        committee: [] for committee in dict.fromkeys(committee_by_prefix.values())
    }
    first_congress = _congress_for_date(start_date)
    current_congress = _congress_for_date(today)

    for congress in range(
        min(first_congress, current_congress),
        max(first_congress, current_congress) + 1,
    ):
        congress_start = datetime(
            1789 + (congress - 1) * 2,
            1,
            3,
            tzinfo=timezone.utc,
        )
        requested_coverage = max(
            congress_start,
            datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
            - timedelta(days=Config.CONGRESS_INITIAL_LOOKBACK_DAYS),
        )
        for record in _sync_meetings(congress, chamber.lower(), requested_coverage):
            detail = record.get("detail") or {}
            meeting_type = str(detail.get("type") or "")
            title = " ".join(str(detail.get("title") or "").split())
            if "hearing" not in meeting_type.lower():
                continue
            try:
                meeting_date = _parse_utc(detail.get("date")).astimezone(EASTERN)
            except (AttributeError, TypeError, ValueError):
                continue
            if meeting_date.date() < start_date:
                continue

            committee = None
            for api_committee in detail.get("committees") or []:
                prefix = str(api_committee.get("systemCode") or "").lower()[:4]
                if prefix in committee_by_prefix:
                    committee = committee_by_prefix[prefix]
                    break
            if not committee or not title:
                continue

            status = str(detail.get("meetingStatus") or "").strip()
            if status and status.lower() not in {"scheduled", "completed"}:
                title = f"[{status}] {title}"
            event_id = str(detail.get("eventId") or "")
            public_url = (
                f"https://www.congress.gov/event/{congress}th-Congress/"
                f"{chamber.lower()}-event/{event_id}"
            )
            grouped[committee].append(
                {
                    "title": title,
                    "url": public_url,
                    "date": meeting_date,
                    "tag": "hearing",
                }
            )

    for hearings in grouped.values():
        unique = {item["url"]: item for item in hearings}
        hearings[:] = sorted(
            unique.values(),
            key=lambda item: item["date"],
            reverse=True,
        )
    return grouped
