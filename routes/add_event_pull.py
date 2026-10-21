# routes/add_event_pull.py
from __future__ import annotations

from datetime import datetime, date
from io import BytesIO
from xml.sax.saxutils import escape, quoteattr

from flask import Blueprint, render_template, request, send_file, url_for, redirect, abort, make_response, session, jsonify
from features.categorize import categorize_article, CATEGORIES
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

    return render_template(
        "add_event_pull.html",
        start_date=start_str,
        end_date=end_str,
        grouped=grouped,
        pulled=pulled,
        error=error,
        addevent_calendar_href="https://app.addevent.com/calendars/GT179952",
        categorize_ready=categorize_ready,
    )

@add_event_pull.route("/add-event-pull/export", methods=["GET"])
def add_event_pull_export_pdf():
    # Require built categories that match current pulled set
    cache = session.get("addevent_categories_cache") or {}
    events_min = session.get("addevent_pulled") or []
    if not cache.get("index") or not events_min:
        return redirect(url_for("add_event_pull.add_event_categories_review"))
    if cache.get("sig") != _event_signature(events_min):
        return redirect(url_for("add_event_pull.add_event_categories_review"))

    # Use last pulled range (or explicit query args) to re-pull full event objects
    last_range = session.get("addevent_last_range") or {}
    start_str = request.args.get("start") or last_range.get("start")
    end_str   = request.args.get("end")   or last_range.get("end")
    if not (start_str and end_str):
        return redirect(url_for("add_event_pull.add_event_categories_review"))

    start = _parse_date(start_str)
    end   = _parse_date(end_str)
    if not start or not end or end < start:
        abort(400, "Invalid date range")

    # Re-pull full events so PDF has full fields (starts_at_dt, original_link, etc.)
    events_full = search_events_between(start, end, calendar_key=DEFAULT_CALENDAR_KEY) or []
    by_id = {str((e.get("id") if isinstance(e, dict) else getattr(e, "id", ""))): e for e in events_full}

    # Build ordered categories from cache index -> list of full event objs
    index = cache.get("index") or {}
    preferred = [*CATEGORIES]
    ordered = OrderedDict()

    # helper to get printable dt inside template
    def _attach_dt(ev):
        # ensure attribute access works in Jinja either way
        if isinstance(ev, dict):
            return ev
        return ev  # Jinja handles attr/item lookup; no change needed

    for lab in preferred:
        if lab in index:
            items = []
            for ref in index[lab] or []:
                ev = by_id.get(str(ref))
                if ev:
                    items.append(_attach_dt(ev))
            if items:
                ordered[lab] = items

    # append any unexpected categories
    for lab, refs in index.items():
        if lab in ordered:
            continue
        items = []
        for ref in refs or []:
            ev = by_id.get(str(ref))
            if ev:
                items.append(_attach_dt(ev))
        if items:
            ordered[lab] = items

    if not ordered:
        # nothing matched the current range; bounce to review
        return redirect(url_for("add_event_pull.add_event_categories_review"))

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception as exc:
        return make_response(
            f"PDF export is unavailable in this deployment environment: {exc}",
            503,
        )

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title="AddEvent Categories",
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.fontName = "Helvetica-Bold"
    title_style.fontSize = 20
    title_style.leading = 24

    heading_style = styles["Heading2"]
    heading_style.fontName = "Helvetica-Bold"
    heading_style.fontSize = 14
    heading_style.leading = 18
    heading_style.spaceBefore = 12
    heading_style.spaceAfter = 6
    heading_style.textColor = colors.HexColor("#111827")

    body_style = ParagraphStyle(
        "AddEventBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#111827"),
        spaceAfter=2,
    )
    link_style = ParagraphStyle(
        "AddEventLink",
        parent=body_style,
        textColor=colors.HexColor("#1d4ed8"),
    )
    date_style = ParagraphStyle(
        "AddEventDate",
        parent=body_style,
        fontName="Helvetica-Bold",
    )

    story = [
        Paragraph("AddEvent Categories", title_style),
        Spacer(1, 0.15 * inch),
    ]

    for label, items in ordered.items():
        if not items:
            continue

        story.append(Paragraph(escape(label), heading_style))
        rows = [[
            Paragraph("Date", date_style),
            Paragraph("Title", date_style),
            Paragraph("Links", date_style),
        ]]

        for ev in items:
            starts_at_dt = ev.get("starts_at_dt") if isinstance(ev, dict) else getattr(ev, "starts_at_dt", None)
            when_text = ev.get("when_text") if isinstance(ev, dict) else getattr(ev, "when_text", "")
            title = ev.get("title") if isinstance(ev, dict) else getattr(ev, "title", "")
            original_link = ev.get("original_link") if isinstance(ev, dict) else getattr(ev, "original_link", "")
            addevent_url = ev.get("addevent_url") if isinstance(ev, dict) else getattr(ev, "addevent_url", "")
            event_id = ev.get("id") if isinstance(ev, dict) else getattr(ev, "id", "")

            if starts_at_dt:
                date_text = escape(starts_at_dt.strftime("%Y-%m-%d %H:%M"))
            elif when_text:
                date_text = escape(str(when_text))
            else:
                date_text = "—"

            title_html = escape(title or "")
            if original_link:
                title_html = f'<link href={quoteattr(original_link)} color="blue">{title_html}</link>'

            links_html = []
            if original_link:
                links_html.append(
                    f'<b>Link:</b> <link href={quoteattr(original_link)} color="blue">{escape(original_link)}</link>'
                )
            elif addevent_url:
                links_html.append(
                    f'<b>Calendar:</b> <link href={quoteattr(addevent_url)} color="blue">{escape(addevent_url)}</link>'
                )

            if event_id:
                ics_url = url_for("add_event_pull.add_event_pull_event_ics", event_id=event_id, _external=True)
                links_html.append(
                    f'<b>ICS:</b> <link href={quoteattr(ics_url)} color="blue">{escape(ics_url)}</link>'
                )

            if not links_html:
                links_html.append("<i>No link found.</i>")

            rows.append([
                Paragraph(date_text, body_style),
                Paragraph(title_html or "&mdash;", link_style),
                Paragraph("<br/>".join(links_html), link_style),
            ])

        table = Table(rows, colWidths=[1.45 * inch, 3.2 * inch, 2.65 * inch], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.white),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#6b7280")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#e5e7eb")),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f9fafb")),
            ("BOX", (0, 1), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
            ("INNERGRID", (0, 1), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 1), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.14 * inch))

    story.append(Spacer(1, 0.12 * inch))
    story.append(Paragraph(f"Generated {escape(datetime.now().strftime('%Y-%m-%d %H:%M'))}", body_style))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    fname = f"addevent-categories-{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}.pdf"
    return send_file(BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True, download_name=fname)


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
    url   = (ev.get("original_link") or ev.get("addevent_url") or "")[:300]
    date_str = ev.get("date_text") or ""
    time_str = ev.get("time_text") or ""
    if date_str and time_str:
        date_str = f"{date_str} {time_str}"
    elif not date_str:
        date_str = ev.get("starts_at") or ev.get("when_text") or ev.get("start") or ""
    if isinstance(date_str, (datetime, date)):
        date_str = date_str.isoformat()
    return {
        "id": ev.get("id"),
        "title": title,
        "url": url,
        "date": (date_str or "")[:40],
        "source": "addevent",
    }

def _event_signature(events: list[dict]) -> str:
    base = [(str(e.get("id")), e.get("title") or "") for e in events]
    return hashlib.sha1(json.dumps(sorted(base), separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()

def _resolve_event_ref(ref: str, events_by_id: dict[str, dict]) -> dict | None:
    return events_by_id.get(str(ref))

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

    index = cache.get("index") or {}
    events = session.get("addevent_pulled") or []
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

    last_range = session.get("addevent_last_range") or {}
    return render_template(
        "add_event_categories.html",
        categories=ordered,
        built_at=cache.get("built_at"),
        last_range=last_range, 
    )

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
