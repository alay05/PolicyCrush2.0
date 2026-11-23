from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path

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
