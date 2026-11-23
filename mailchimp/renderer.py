from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from features.categorize import SPECIAL_CALENDAR


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "mailchimp"
_environment = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(("html", "xml")),
)


def _linked_headline(article: dict) -> Markup:
    headline = str(article.get("headline") or "").strip()
    url = str(article.get("url") or "").strip()
    if not headline or not url:
        return Markup(escape(headline))

    link_text = str(article.get("link_text") or "").strip()
    if not link_text or link_text not in headline:
        link_text = headline
    start = headline.find(link_text)
    end = start + len(link_text)
    return Markup(
        f"{escape(headline[:start])}"
        f'<a href="{escape(url)}" target="_blank" style="color:#0d92da;text-decoration:none;">'
        f"{escape(link_text)}</a>{escape(headline[end:])}"
    )


def _event_time(article: dict) -> str:
    value = article.get("date")
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    hour = parsed.hour % 12 or 12
    return f"{hour}:{parsed.minute:02d}{parsed.strftime('%p')}"


def _newsletter_context(categories) -> dict:
    sections = []
    for label, items in categories.items():
        if not items:
            continue
        sections.append(
            {
                "label": "Calendar" if label == SPECIAL_CALENDAR else label,
                "items": [
                    {
                        "headline_html": _linked_headline(article),
                        "event_time": _event_time(article) if label == SPECIAL_CALENDAR else "",
                        "sub_articles": [
                            {"headline_html": _linked_headline(child),
                             "event_time": _event_time(child) if label == SPECIAL_CALENDAR else ""}
                            for child in article.get("sub_articles", [])
                        ],
                    }
                    for article in items
                ],
            }
        )

    return {"sections": sections}


def render_main_newsletter(categories) -> tuple[str, str]:
    html = _environment.get_template("main_newsletter.html").render(**_newsletter_context(categories))
    return html, sha256(html.encode("utf-8")).hexdigest()


def render_main_newsletter_sections(categories) -> dict[str, str]:
    """Render the same content as the full email, without its template shell."""
    template = _environment.get_template("main_newsletter.html")
    context = template.new_context(_newsletter_context(categories))
    return {
        name: "".join(template.blocks[name](context))
        for name in ("greeting", "body", "footnote")
    }


def _w2w4_date(event: dict) -> str:
    # The saved date begins with the event's already-localized ISO date.
    value = str(event.get("date") or "").strip()
    try:
        parsed = datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        label = str(event.get("date_label") or "").strip()
        try:
            parsed = datetime.strptime(label, "%a, %b %d, %Y")
        except ValueError:
            return label
    return f"{parsed.month}/{parsed.day}"


def _w2w4_start_time(event: dict) -> str:
    # The reference newsletter displays only the start time, including EST/EDT.
    label = str(event.get("time_label") or "").strip()
    start = label.split(" – ", 1)[0]
    return re.sub(r"\s+(AM|PM)\b", r"\1", start)


def _outlook_calendar_url(value: str) -> str:
    parts = urlsplit(value)
    if (parts.scheme in {"http", "https"}
            and parts.hostname in {"addevent.com", "www.addevent.com"}
            and re.fullmatch(r"/event/[a-zA-Z0-9]+(?:\+[a-zA-Z0-9]+)?/?", parts.path)):
        path = parts.path.rstrip("/").split("+", 1)[0] + "+outlook"
        return urlunsplit(parts._replace(path=path))
    return value


def _w2w4_headline(event: dict, headline: str) -> Markup:
    link_text = str(event.get("link_text") or "").strip()
    if not link_text or link_text not in headline:
        match = re.search(r"\b(Hearing|Hrg|Meeting|Mtg|Webinar|Briefing|Conference|Workshop)\b", headline, re.I)
        if match:
            word = match.group()
            link_text = {"hearing": "Hrg", "meeting": "Mtg"}.get(word.lower(), word)
            headline = headline[:match.start()] + link_text + headline[match.end():]
    return _linked_headline({**event, "headline": headline, "link_text": link_text})


def _w2w4_context(categories) -> dict:
    sections = []
    for label, events in categories.items():
        if not events:
            continue
        items = []
        for event in events:
            headline = str(event.get("headline") or "").strip()
            schedule = " · ".join(
                str(event.get(key) or "").strip()
                for key in ("date_label", "time_label") if event.get(key)
            )
            # Generated event headlines already end with this exact schedule.
            # Display it once, separately from the linked title. Preserve user edits.
            suffix = f" — {schedule}"
            if schedule and headline.endswith(suffix):
                headline = headline[:-len(suffix)]
            items.append({
                "headline_html": _w2w4_headline(event, headline),
                "date": _w2w4_date(event),
                "start_time": _w2w4_start_time(event),
                "calendar_url": _outlook_calendar_url(
                    event.get("calendar_url") or event.get("addevent_url") or ""
                ),
            })
        sections.append({"label": label, "items": items})
    return {"sections": sections}


def render_w2w4_newsletter(categories) -> tuple[str, str]:
    html = _environment.get_template("w2w4_newsletter.html").render(**_w2w4_context(categories))
    return html, sha256(html.encode("utf-8")).hexdigest()


def render_w2w4_newsletter_sections(categories) -> dict[str, str]:
    template = _environment.get_template("w2w4_newsletter.html")
    context = template.new_context(_w2w4_context(categories))
    return {
        name: "".join(template.blocks[name](context))
        for name in ("greeting", "body", "footnote")
    }
