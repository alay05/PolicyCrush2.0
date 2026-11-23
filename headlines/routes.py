from collections import OrderedDict
from datetime import datetime

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from config import Config
from features.calendar import EventImportError, create_event_addevent, event_from_url
from headlines.generator import HeadlineGenerationError, generate_headline_records
from headlines.state import ALL_CATEGORIES, get_current_workflow
from mailchimp.client import MailchimpClient
from mailchimp.renderer import render_main_newsletter, render_main_newsletter_sections
from mailchimp.workflow import create_or_update_draft, mailchimp_draft_stale


headlines = Blueprint("headlines", __name__, template_folder="templates")


def _workflow_categories(workflow) -> OrderedDict:
    items = workflow["items"]
    index = workflow["index"]
    parents = workflow.get("parents") or {}
    return OrderedDict(
        (
            category,
            [
                {**items[article_id], "sub_articles": [
                    items[child_id] for child_id in index.get(category, [])
                    if child_id in items and parents.get(child_id) == article_id
                ]}
                for article_id in index.get(category, [])
                if article_id in items and article_id not in parents
            ],
        )
        for category in ALL_CATEGORIES
    )


@headlines.post("/generate")
def generate():
    saved = list(session.get("saved_articles") or [])
    if not saved:
        flash("Save at least one article before generating headlines.", "info")
        return redirect(url_for("saved_articles.saved_articles_view"))

    saved_by_id = {str(article.get("id")): article for article in saved}
    workflow = get_current_workflow(saved)
    existing_ids = set(workflow["items"]) if workflow else set()
    articles_to_generate = [
        article
        for article in saved
        if str(article.get("id")) not in existing_ids
    ]

    if not articles_to_generate:
        return redirect(url_for("headlines.review"))

    try:
        generated = generate_headline_records(articles_to_generate)
    except HeadlineGenerationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("saved_articles.saved_articles_view"))

    items = dict(workflow["items"]) if workflow else {}
    index = {
        category: list((workflow["index"] if workflow else {}).get(category, []))
        for category in ALL_CATEGORIES
    }

    for result in generated:
        article_id = str(result["id"])
        source = saved_by_id[article_id]
        item = {
            **source,
            "original_title": source.get("title", ""),
            "headline": result["headline"],
            "link_text": result.get("link_text") or result["headline"],
        }
        items[article_id] = item
        index[result["category"]].append(article_id)

    next_workflow = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "items": items,
        "index": index,
        "parents": dict(workflow.get("parents") or {}) if workflow else {},
    }
    if workflow and workflow.get("mailchimp_draft"):
        next_workflow["mailchimp_draft"] = workflow["mailchimp_draft"]
    session["headline_workflow"] = next_workflow
    session.modified = True
    return redirect(url_for("headlines.review"))


@headlines.get("")
def review():
    saved = list(session.get("saved_articles") or [])
    workflow = get_current_workflow(saved)
    if not workflow:
        flash("Generate headlines from the current saved articles first.", "info")
        return redirect(url_for("saved_articles.saved_articles_view"))

    pending_count = len(
        {str(article.get("id")) for article in saved} - set(workflow["items"])
    )
    categories = _workflow_categories(workflow)
    _, content_hash = render_main_newsletter(categories)
    mailchimp_draft = workflow.get("mailchimp_draft") or {}
    return render_template(
        "headlines/review.html",
        categories=categories,
        page_title="Main Newsletter — Finalize",
        built_at=workflow.get("built_at"),
        pending_count=pending_count,
        move_url=url_for("headlines.move"),
        nesting_enabled=True,
        rename_url=url_for("headlines.rename"),
        calendar_import_url=url_for("headlines.add_to_calendar"),
        generate_url=url_for("headlines.generate"),
        back_url=url_for("saved_articles.saved_articles_view"),
        back_label="← Saved Articles",
        mailchimp_enabled=True,
        mailchimp_configured=bool(Config.MAILCHIMP_API_KEY and Config.MAILCHIMP_TEMPLATE_ID),
        mailchimp_draft=mailchimp_draft,
        mailchimp_stale=mailchimp_draft_stale(mailchimp_draft, content_hash),
        mailchimp_action_url=url_for("headlines.mailchimp_draft"),
    )


@headlines.post("/add-to-calendar")
def add_to_calendar():
    """Import a reviewed hearing without changing newsletter content or draft state."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not payload.get("id"):
        return jsonify(ok=False, error="Missing article ID"), 400
    article_id = str(payload["id"])
    workflow = get_current_workflow()
    if not workflow:
        return jsonify(ok=False, error="Generate headlines before adding a hearing to the calendar."), 409
    article = workflow["items"].get(article_id)
    if not article:
        return jsonify(ok=False, error="Article not found in the current review."), 404
    if article.get("section") != "hearing" or article_id not in workflow["index"].get("Events", []):
        return jsonify(ok=False, error="Only hearings in Events can be added to the calendar."), 400
    try:
        event = event_from_url(article.get("url") or "")
        saved = create_event_addevent(event)
    except EventImportError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    except Exception:
        current_app.logger.exception("Headline review calendar import failed")
        return jsonify(ok=False, error="The event could not be imported. Check the calendar before retrying."), 502
    return jsonify(ok=True, deduped=bool(saved.get("deduped")))


@headlines.post("/mailchimp")
def mailchimp_draft():
    saved = list(session.get("saved_articles") or [])
    workflow = get_current_workflow(saved)
    if not workflow:
        flash("Generate headlines before creating a Mailchimp draft.", "info")
        return redirect(url_for("saved_articles.saved_articles_view"))

    saved_ids = {str(article.get("id")) for article in saved}
    if saved_ids - set(workflow["items"]):
        flash("Generate all pending headlines before creating a Mailchimp draft.", "error")
        return redirect(url_for("headlines.review"))

    categories = _workflow_categories(workflow)
    _, content_hash = render_main_newsletter(categories)
    sections = render_main_newsletter_sections(categories)
    return create_or_update_draft(
        workflow,
        session_key="headline_workflow",
        review_endpoint="headlines.review",
        content_hash=content_hash,
        sections=sections,
        client_factory=MailchimpClient,
    )


@headlines.post("/rename")
def rename():
    payload = request.get_json(silent=True) or {}
    article_id = str(payload.get("id") or "").strip()
    headline = str(payload.get("headline") or "").strip()
    if not article_id or not headline:
        return jsonify(ok=False, error="Missing article ID or headline"), 400
    if len(headline) > 500:
        return jsonify(ok=False, error="Headline is too long"), 400

    workflow = get_current_workflow()
    if not workflow:
        return jsonify(ok=False, error="No current headline workflow"), 409
    if article_id not in workflow["items"]:
        return jsonify(ok=False, error="Article not found"), 404

    item = workflow["items"][article_id]
    item["headline"] = headline
    if not item.get("link_text") or item["link_text"] not in headline:
        item["link_text"] = headline
    workflow["built_at"] = datetime.now().isoformat(timespec="seconds")
    session["headline_workflow"] = workflow
    session.modified = True
    return jsonify(ok=True)


@headlines.post("/move")
def move():
    payload = request.get_json(silent=True) or {}
    article_id = str(payload.get("id") or "").strip()
    to_category = str(payload.get("to_category") or "").strip()
    parent_id = str(payload.get("parent_id") or "").strip()
    new_index = payload.get("new_index")

    if not article_id or to_category not in ALL_CATEGORIES or new_index is None:
        return jsonify(ok=False, error="Invalid move request"), 400
    try:
        new_index = int(new_index)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Invalid destination index"), 400

    workflow = get_current_workflow()
    if not workflow:
        return jsonify(ok=False, error="No current headline workflow"), 409

    index = workflow["index"]
    parents = dict(workflow.get("parents") or {})
    if article_id not in workflow["items"]:
        return jsonify(ok=False, error="Article not found"), 404

    children = [child for ids in index.values() for child in ids if parents.get(child) == article_id]
    if parent_id:
        if parent_id not in index[to_category]:
            return jsonify(ok=False, error="Parent article not found in destination category"), 400
        if parent_id == article_id or parent_id in parents or children:
            return jsonify(ok=False, error="Sub-articles can only attach to a main article. Detach existing sub-articles first."), 400

    moving_ids = [article_id, *children]
    for category in index:
        index[category] = [item_id for item_id in index[category] if item_id not in moving_ids]
    parents.pop(article_id, None)
    destination = index.setdefault(to_category, [])
    if parent_id:
        siblings = [item_id for item_id in destination if parents.get(item_id) == parent_id]
        position = max(0, min(new_index, len(siblings)))
        anchor = siblings[position - 1] if position else parent_id
        insertion_index = destination.index(anchor) + 1
        parents[article_id] = parent_id
    else:
        roots = [item_id for item_id in destination if item_id not in parents]
        position = max(0, min(new_index, len(roots)))
        insertion_index = destination.index(roots[position]) if position < len(roots) else len(destination)
    destination[insertion_index:insertion_index] = moving_ids
    workflow["index"] = index
    workflow["parents"] = parents
    workflow["built_at"] = datetime.now().isoformat(timespec="seconds")
    session["headline_workflow"] = workflow
    session.modified = True
    return jsonify(ok=True)
