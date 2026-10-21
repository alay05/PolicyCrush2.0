import hashlib
from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for


saved_articles = Blueprint("saved_articles", __name__)

TOOL_ENDPOINTS = {
    "news": "news.news_view",
    "house": "house.house_view",
    "senate": "senate.senate_view",
}

TOOL_LABELS = {
    "news": "Daily",
    "house": "House",
    "senate": "Senate",
}


def _article_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _serialize_date(value) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value or "")


def prepare_article(article: dict, tool: str, source: str, section: str = "") -> dict:
    """Return a display- and session-safe article record."""
    url = str(article.get("url") or "").strip()
    title = str(article.get("title") or "").strip()
    section = str(section or "").strip()
    source = str(source or "").strip()

    label_parts = [TOOL_LABELS[tool]]
    if source:
        label_parts.append(source)
    if section:
        label_parts.append(section.title())

    prepared = {
        "id": _article_id(url),
        "title": title,
        "url": url,
        "date": _serialize_date(article.get("date")),
        "tool": tool,
        "source": source,
        "section": section,
        "source_label": " — ".join(label_parts),
    }
    if article.get("suggestion"):
        prepared["suggestion"] = str(article["suggestion"])
    return prepared


def store_manual_pull(tool: str, results, items: list[dict], input_date: str, use_openai: bool) -> None:
    caches = dict(session.get("manual_article_caches") or {})
    caches[tool] = {
        "results": results,
        "items": {item["id"]: item for item in items},
        "input_date": input_date,
        "use_openai": bool(use_openai),
    }
    session["manual_article_caches"] = caches
    session.modified = True


def get_manual_pull(tool: str) -> dict:
    return (session.get("manual_article_caches") or {}).get(tool) or {}


def _saved_sort_key(article: dict):
    publication_date = article.get("date") or ""
    return bool(publication_date), publication_date, article.get("title") or ""


@saved_articles.get("/saved-articles")
def saved_articles_view():
    articles = sorted(
        session.get("saved_articles") or [],
        key=_saved_sort_key,
        reverse=True,
    )
    return render_template("saved_articles.html", articles=articles)


@saved_articles.post("/saved-articles/add/<tool>")
def add_saved_articles(tool: str):
    if tool not in TOOL_ENDPOINTS:
        abort(404)

    cached_items = get_manual_pull(tool).get("items") or {}
    selected_ids = request.form.getlist("selected")
    saved = list(session.get("saved_articles") or [])
    saved_urls = {(article.get("url") or "").strip() for article in saved}
    added_count = 0
    skipped_count = 0

    for article_id in selected_ids:
        article = cached_items.get(article_id)
        if not article:
            continue
        url = (article.get("url") or "").strip()
        if not url or url in saved_urls:
            skipped_count += 1
            continue
        saved.append(dict(article))
        saved_urls.add(url)
        added_count += 1

    session["saved_articles"] = saved
    session.modified = True

    if added_count:
        message = f"Saved {added_count} article{'s' if added_count != 1 else ''}."
        if skipped_count:
            message += f" Skipped {skipped_count} duplicate{'s' if skipped_count != 1 else ''}."
        flash(message, "success")
    elif skipped_count:
        flash("Those articles are already saved.", "info")
    else:
        flash("Select at least one article to save.", "info")

    return redirect(url_for(TOOL_ENDPOINTS[tool]))


@saved_articles.post("/saved-articles/<article_id>/remove")
def remove_saved_article(article_id: str):
    saved = list(session.get("saved_articles") or [])
    remaining = [article for article in saved if article.get("id") != article_id]
    session["saved_articles"] = remaining
    session.modified = True

    if len(remaining) < len(saved):
        flash("Article removed.", "success")
    else:
        flash("That article was not found.", "info")
    return redirect(url_for("saved_articles.saved_articles_view"))
