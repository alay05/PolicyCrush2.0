# routes/add_event_pull.py
from __future__ import annotations

from datetime import datetime, date
from io import BytesIO

from flask import Blueprint, render_template, request, send_file, url_for, redirect, abort, session, jsonify, flash
from config import Config
from features.categorize import categorize_article, CATEGORIES
from headlines.generator import HeadlineGenerationError, generate_event_headline_records
from mailchimp.client import MailchimpClient
from mailchimp.renderer import render_w2w4_newsletter, render_w2w4_newsletter_sections
from mailchimp.workflow import create_or_update_draft, mailchimp_draft_stale
from collections import OrderedDict
import hashlib, json

from features.calendar_pull import (
    search_events_between,
    retrieve_event,
    make_ics_for_event,
    group_by_day,
    DEFAULT_CALENDAR_KEY,
)

add_event_pull = Blueprint("add_event_pull", __name__)


def _event_value(ev, key: str, default=""):
    if isinstance(ev, dict):
        return ev.get(key, default)
    return getattr(ev, key, default)


def _friendly_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
        return parsed.strftime("%a, %b %d, %Y").replace(" 0", " ")
    except (TypeError, ValueError):
        return str(value)


def _event_when_parts(ev) -> tuple[str, str]:
    """Return compact, human-readable date and time labels for an event."""
    date_text = str(_event_value(ev, "date_text") or "")
    time_text = str(_event_value(ev, "time_text") or "")
    end_date_text = str(_event_value(ev, "end_date_text") or "")
    end_time_text = str(_event_value(ev, "end_time_text") or "")

    starts_at_dt = _event_value(ev, "starts_at_dt", None)
    if not date_text and starts_at_dt:
        date_text = starts_at_dt.strftime("%Y-%m-%d")
    date_label = _friendly_date(date_text) or "Date unavailable"

    if time_text == "All day":
        return date_label, time_text
    if time_text and end_time_text:
        if end_date_text and date_text and end_date_text != date_text:
            return date_label, f"{time_text} – {_friendly_date(end_date_text)}, {end_time_text}"
        return date_label, f"{time_text} – {end_time_text}"
    if time_text:
        return date_label, time_text
    if starts_at_dt:
        return date_label, starts_at_dt.strftime("%I:%M %p").lstrip("0")
    return date_label, "Time unavailable"


def _current_event_headline_workflow(events: list[dict] | None = None):
    events = list(events if events is not None else session.get("addevent_pulled") or [])
    event_by_id = {str(event.get("id")): event for event in events}
    cache = session.get("addevent_categories_cache") or {}
    raw_items = cache.get("items")
    raw_index = cache.get("index")
    if not event_by_id or not isinstance(raw_items, dict) or not isinstance(raw_index, dict):
        return None

    compared_fields = ("title", "url", "addevent_url", "date", "date_label", "time_label", "location")
    items = {
        event_id: item
        for event_id, item in raw_items.items()
        if event_id in event_by_id
        and all(item.get(field) == event_by_id[event_id].get(field) for field in compared_fields)
    }
    if not items:
        return None

    index = {category: [] for category in CATEGORIES}
    placed = set()
    for category in CATEGORIES:
        for event_id in raw_index.get(category, []):
            event_id = str(event_id)
            if event_id in items and event_id not in placed:
                index[category].append(event_id)
                placed.add(event_id)
    for event_id in items:
        if event_id not in placed:
            index["Quality and Innovation"].append(event_id)

    if items != raw_items or index != raw_index:
        cache["items"] = items
        cache["index"] = index
        session["addevent_categories_cache"] = cache
        session.modified = True
    return cache


def _event_workflow_categories(workflow) -> OrderedDict:
    items = workflow["items"]
    return OrderedDict(
        (category, [
            {**items[event_id], "calendar_url": items[event_id].get("addevent_url") or url_for(
                "add_event_pull.add_event_pull_event_ics", event_id=event_id, _external=True,
            )}
            for event_id in workflow["index"].get(category, []) if event_id in items
        ])
        for category in CATEGORIES
    )


def _event_headline_status(events: list[dict]) -> tuple[int, int]:
    workflow = _current_event_headline_workflow(events)
    generated_ids = set(workflow["items"]) if workflow else set()
    event_ids = {str(event.get("id")) for event in events}
    return len(generated_ids & event_ids), len(event_ids - generated_ids)

def _parse_date(s: str, fallback: date | None = None) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return fallback

@add_event_pull.route("/add-event-pull", methods=["GET", "POST"])
def add_event_pull_home():
    today = date.today()
    default_start = today
    default_end = today

    start_str = request.form.get("start_date") or request.args.get("start")
    end_str   = request.form.get("end_date")   or request.args.get("end")


    pulled, grouped, error = [], {}, None

    # NEW: default + compute from session so GET works
    categorize_ready = False
    cur_events = session.get("addevent_pulled") or []
    if request.method == "GET" and cur_events and (not start_str or not end_str):
        last_range = session.get("addevent_last_range") or {}
        start_str = start_str or last_range.get("start")
        end_str = end_str or last_range.get("end")
    if cur_events:
        cur_sig = _event_signature(cur_events)
        cache = session.get("addevent_categories_cache") or {}
        categorize_ready = bool(cache.get("sig") == cur_sig and cache.get("index"))

    if request.method == "POST":
        start = _parse_date(start_str, default_start)
        end   = _parse_date(end_str, default_end)
        if not start or not end:
            error = "Please provide valid Start and End dates (YYYY-MM-DD)."
        elif end < start:
            error = "End date must be on or after Start date."
        else:
            try:
                events  = search_events_between(start, end, calendar_key=DEFAULT_CALENDAR_KEY)
                pulled  = events
                grouped = group_by_day(events)

                session["addevent_pulled"] = [_event_minimal(ev) for ev in (events or [])]
                session.modified = True

                # Recompute after updating session
                cur_events = session.get("addevent_pulled") or []
                cur_sig = _event_signature(cur_events)
                cache = session.get("addevent_categories_cache") or {}
                categorize_ready = bool(cache.get("sig") == cur_sig and cache.get("index"))
            except Exception as e:
                print("AddEvent pull error:", e)
                error = "Couldn't pull events from AddEvent. Check API key and try again."

        start_str = (start or default_start).strftime("%Y-%m-%d")
        end_str   = (end   or default_end  ).strftime("%Y-%m-%d")
        session["addevent_last_range"] = {"start": start_str, "end": end_str}
        session.modified = True

    # GET (initial) – keep defaults visible
    if request.method == "GET" and (not start_str or not end_str):
        start_str = default_start.strftime("%Y-%m-%d")
        end_str   = default_end.strftime("%Y-%m-%d")
        session["addevent_last_range"] = {"start": start_str, "end": end_str}
        session.modified = True

    generated_count, pending_count = _event_headline_status(cur_events)
    return render_template(
        "add_event_pull.html",
        start_date=start_str,
        end_date=end_str,
        grouped=grouped,
        pulled=pulled,
        error=error,
        addevent_calendar_href="https://app.addevent.com/calendars/GT179952",
        categorize_ready=categorize_ready,
        generated_count=generated_count,
        pending_count=pending_count,
        friendly_date=_friendly_date,
    )

@add_event_pull.route("/add-event-pull/ics/<event_id>.ics", methods=["GET"])
def add_event_pull_event_ics(event_id: str):
    """
    Build and return a per-event .ics using live data from AddEvent.
    """
    ev = retrieve_event(event_id)
    if not ev:
        abort(404, "Event not found")

    ics = make_ics_for_event(ev)
    fname = f"addevent-{event_id}.ics"
    return send_file(
        BytesIO(ics.encode("utf-8")),
        mimetype="text/calendar; charset=utf-8",
        as_attachment=True,
        download_name=fname,
    )

def _event_minimal(ev: dict) -> dict:
    """Normalize an AddEvent record into the minimal shape used for categorizing."""
    title = (ev.get("title") or "")[:240]  # trim to keep cookie small
    url   = ev.get("original_link") or ev.get("addevent_url") or ""
    date_only = ev.get("date_text") or ""
    date_str = date_only
    time_str = ev.get("time_text") or ""
    if date_str and time_str:
        date_str = f"{date_str} {time_str}"
    elif not date_str:
        date_str = ev.get("starts_at") or ev.get("when_text") or ev.get("start") or ""
    if isinstance(date_str, (datetime, date)):
        date_str = date_str.isoformat()
    date_label = _friendly_date(str(date_only)) if date_only else ""
    time_label = _event_when_parts(ev)[1] if date_only else time_str
    return {
        "id": ev.get("id"),
        "title": title,
        "url": url,
        "addevent_url": ev.get("addevent_url") or "",
        "date": (date_str or "")[:40],
        "date_label": date_label,
        "time_label": time_label[:80],
        "location": (ev.get("location") or "")[:180],
        "source": "addevent",
    }

def _event_signature(events: list[dict]) -> str:
    base = [(str(e.get("id")), e.get("title") or "") for e in events]
    return hashlib.sha1(json.dumps(sorted(base), separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()

def _resolve_event_ref(ref: str, events_by_id: dict[str, dict]) -> dict | None:
    return events_by_id.get(str(ref))


@add_event_pull.post("/add-event-pull/generate-headlines")
def add_event_pull_generate_headlines():
    events = list(session.get("addevent_pulled") or [])
    if not events:
        flash("Pull at least one event before generating headlines.", "info")
        return redirect(url_for("add_event_pull.add_event_pull_home"))

    events_by_id = {str(event.get("id")): event for event in events}
    workflow = _current_event_headline_workflow(events)
    existing_ids = set(workflow["items"]) if workflow else set()
    events_to_generate = [
        event for event in events if str(event.get("id")) not in existing_ids
    ]
    if not events_to_generate:
        return redirect(url_for("add_event_pull.add_event_categories_review"))

    try:
        generated = generate_event_headline_records(events_to_generate)
    except HeadlineGenerationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("add_event_pull.add_event_pull_home"))

    items = dict(workflow["items"]) if workflow else {}
    index = {
        category: list((workflow["index"] if workflow else {}).get(category, []))
        for category in CATEGORIES
    }
    for result in generated:
        event_id = str(result["id"])
        source = events_by_id[event_id]
        items[event_id] = {
            **source,
            "original_title": source.get("title", ""),
            "headline": result["headline"],
        }
        index[result["category"]].append(event_id)

    next_workflow = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "sig": _event_signature(events),
        "count": len(events),
        "items": items,
        "index": index,
    }
    if workflow and workflow.get("mailchimp_draft"):
        next_workflow["mailchimp_draft"] = workflow["mailchimp_draft"]
    session["addevent_categories_cache"] = next_workflow
    session["addevent_categorize_ready"] = True
    session.modified = True
    return redirect(url_for("add_event_pull.add_event_categories_review"))

@add_event_pull.post("/add-event-pull/build-categories")
def add_event_pull_build_categories():
    """Build (or rebuild) a categories index for the *current pulled* AddEvent events."""
    events = session.get("addevent_pulled") or []

    # Fallback: if session is empty (e.g., cookie too big or new tab),
    # re-pull using the hidden range fields we added to the form.
    if not events:
        start_str = request.form.get("start") or request.args.get("start")
        end_str   = request.form.get("end")   or request.args.get("end")
        s = _parse_date(start_str)
        e = _parse_date(end_str)
        if s and e and e >= s:
            try:
                fresh = search_events_between(s, e, calendar_key=DEFAULT_CALENDAR_KEY)
                events = [_event_minimal(ev) for ev in (fresh or [])]
                # write back so the review page can hydrate
                session["addevent_pulled"] = events
                session.modified = True
            except Exception as e:
                print("AddEvent pull (build) error:", e)
                return redirect(url_for("add_event_pull.add_event_pull_home"))
        else:
            return redirect(url_for("add_event_pull.add_event_pull_home"))

    # Build signature + cache
    sig = _event_signature(events)
    cache = session.get("addevent_categories_cache") or {}
    if cache.get("sig") == sig and cache.get("index"):
        session["addevent_categorize_ready"] = True
        session.modified = True
        return redirect(url_for("add_event_pull.add_event_categories_review"))

    categories_index = {
        "Congress and the Administration": [],
        "Health Insurance": [],
        "Health Tech": [],
        "Medicaid": [],
        "Medicare": [],
        "Pharmaceuticals and Medical Devices": [],
        "Quality and Innovation": [],
    }

    # AddEvent pulls are all "events"
    for ev in events:
        label = categorize_article(ev.get("title", ""), is_hearing=False)
        if label not in categories_index:
            label = "Quality and Innovation"
        categories_index[label].append(str(ev.get("id")))

    session["addevent_categories_cache"] = {
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sig": sig,
        "count": len(events),
        "index": categories_index,
    }
    session["addevent_categorize_ready"] = True
    session.modified = True
    return redirect(url_for("add_event_pull.add_event_categories_review"))

@add_event_pull.get("/add-event-pull/review")
def add_event_categories_review():
    cache = session.get("addevent_categories_cache")
    if not isinstance(cache, dict) or "index" not in cache:
        return redirect(url_for("add_event_pull.add_event_pull_home"))

    events = session.get("addevent_pulled") or []
    workflow = _current_event_headline_workflow(events)
    if workflow:
        items = workflow["items"]
        event_ids = {str(event.get("id")) for event in events}
        pending_count = len(event_ids - set(items))
        categories = _event_workflow_categories(workflow)
        _, content_hash = render_w2w4_newsletter(categories)
        draft = workflow.get("mailchimp_draft") or {}
        return render_template(
            "headlines/review.html",
            categories=categories,
            page_title="W2W4 — Finalize",
            built_at=workflow.get("built_at"),
            pending_count=pending_count,
            move_url=url_for("add_event_pull.add_event_pull_move_article"),
            rename_url=url_for("add_event_pull.add_event_pull_rename_headline"),
            generate_url=url_for("add_event_pull.add_event_pull_generate_headlines"),
            back_url=url_for("add_event_pull.add_event_pull_home"),
            back_label="← W2W4",
            mailchimp_enabled=True,
            mailchimp_configured=bool(Config.MAILCHIMP_API_KEY and Config.MAILCHIMP_TEMPLATE_ID),
            mailchimp_draft=draft,
            mailchimp_stale=mailchimp_draft_stale(draft, content_hash),
            mailchimp_action_url=url_for("add_event_pull.add_event_pull_mailchimp_draft"),
        )

    index = cache.get("index") or {}
    by_id = {str(e.get("id")): e for e in events}

    hydrated = {}
    for label, refs in index.items():
        items = []
        for ref in refs or []:
            resolved = _resolve_event_ref(ref, by_id)
            if not resolved:
                continue
            item = dict(resolved)
            item["_ref"] = str(ref)  # stick the ref on for the DOM
            items.append(item)
        hydrated[label] = items

    preferred = [*CATEGORIES]
    ordered = OrderedDict((lab, hydrated.get(lab, [])) for lab in preferred if lab in hydrated)
    for lab, items in hydrated.items():
        if lab not in ordered:
            ordered[lab] = items

    return render_template(
        "add_event_categories.html",
        categories=ordered,
        built_at=cache.get("built_at"),
    )


@add_event_pull.post("/add-event-pull/mailchimp")
def add_event_pull_mailchimp_draft():
    events = list(session.get("addevent_pulled") or [])
    workflow = _current_event_headline_workflow(events)
    if not workflow:
        flash("Generate event headlines before creating a Mailchimp draft.", "info")
        return redirect(url_for("add_event_pull.add_event_pull_home"))

    if {str(event.get("id")) for event in events} - set(workflow["items"]):
        flash("Generate all pending headlines before creating a Mailchimp draft.", "error")
        return redirect(url_for("add_event_pull.add_event_categories_review"))

    categories = _event_workflow_categories(workflow)
    _, content_hash = render_w2w4_newsletter(categories)
    return create_or_update_draft(
        workflow,
        session_key="addevent_categories_cache",
        review_endpoint="add_event_pull.add_event_categories_review",
        content_hash=content_hash,
        sections=render_w2w4_newsletter_sections(categories),
        client_factory=MailchimpClient,
    )


@add_event_pull.post("/add-event-pull/rename-headline")
def add_event_pull_rename_headline():
    payload = request.get_json(silent=True) or {}
    event_id = str(payload.get("id") or "").strip()
    headline = str(payload.get("headline") or "").strip()
    if not event_id or not headline:
        return jsonify(ok=False, error="Missing event ID or headline"), 400
    if len(headline) > 500:
        return jsonify(ok=False, error="Headline is too long"), 400

    workflow = _current_event_headline_workflow()
    if not workflow:
        return jsonify(ok=False, error="No current headline workflow"), 409
    if event_id not in workflow["items"]:
        return jsonify(ok=False, error="Event not found"), 404

    workflow["items"][event_id]["headline"] = headline
    workflow["built_at"] = datetime.now().isoformat(timespec="seconds")
    session["addevent_categories_cache"] = workflow
    session.modified = True
    return jsonify(ok=True)

@add_event_pull.post("/add-event-pull/move-article")
def add_event_pull_move_article():
    """
    Body: { id: str, from_category: str|None, to_category: str, new_index: int }
    Mutates session['addevent_categories_cache']['index'].
    """
    payload = request.get_json(silent=True) or {}
    art_id = (payload.get("id") or "").strip()
    from_cat = payload.get("from_category")
    to_cat = payload.get("to_category")
    new_index = payload.get("new_index")

    if not art_id or not to_cat or new_index is None:
        return jsonify(ok=False, error="Missing id/to_category/new_index"), 400

    cache = session.get("addevent_categories_cache")
    if not isinstance(cache, dict) or "index" not in cache:
        return jsonify(ok=False, error="No category index in session"), 400

    index = cache.get("index") or {}
    dest_list = index.setdefault(to_cat, [])

    # try to remove the first matching ref
    removed_ref = None
    if from_cat in index:
        lst = index[from_cat] or []
        for i, ref in enumerate(lst):
            if str(ref) == str(art_id):
                removed_ref = lst.pop(i)
                break
    if removed_ref is None:
        # search all categories if from_cat wasn't accurate
        for lst in index.values():
            for i, ref in enumerate(lst or []):
                if str(ref) == str(art_id):
                    removed_ref = lst.pop(i)
                    break
            if removed_ref is not None:
                break

    if removed_ref is None:
        return jsonify(ok=False, error="Article not found in index"), 404

    insert_at = max(0, min(int(new_index), len(dest_list)))
    dest_list.insert(insert_at, removed_ref)

    cache["index"] = index
    cache["built_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session["addevent_categories_cache"] = cache
    session.modified = True
    return jsonify(ok=True)
