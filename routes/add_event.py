from flask import Blueprint, current_app, render_template, request

from features.calendar import EventImportError, create_event_addevent, event_from_url
from features.calendar_pull import DEFAULT_CALENDAR_KEY

add_event = Blueprint("add_event", __name__)


@add_event.route("/add-event", methods=["GET", "POST"])
def hearing_form():
    result = None
    error = None
    url = (request.form.get("event-url") or "").strip()
    if request.method == "POST":
        if not url:
            error = "Please enter a URL."
        else:
            try:
                event = event_from_url(url)
                saved = create_event_addevent(event)
                result = {
                    "title": saved.get("title") or event["title"],
                    "datetime": saved.get("datetime_start") or event["datetime_start"],
                    "location": saved.get("location", event["location"]),
                    "deduped": saved.get("deduped", False),
                    "addevent_link": f"https://app.addevent.com/calendars/{DEFAULT_CALENDAR_KEY}",
                }
            except EventImportError as exc:
                error = str(exc)
            except Exception:
                current_app.logger.exception("AddEvent import failed")
                error = "The event could not be imported. Please try again."
    return render_template("add_event.html", result=result, error=error, event_url=url)
