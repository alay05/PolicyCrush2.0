from collections import OrderedDict
from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from headlines.generator import HeadlineGenerationError, generate_headline_records
from headlines.state import ALL_CATEGORIES, get_current_workflow


headlines = Blueprint("headlines", __name__, template_folder="templates")


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
        }
        items[article_id] = item
        index[result["category"]].append(article_id)

    session["headline_workflow"] = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "items": items,
        "index": index,
    }
    session.modified = True
    return redirect(url_for("headlines.review"))


@headlines.get("")
def review():
    saved = list(session.get("saved_articles") or [])
    workflow = get_current_workflow(saved)
    if not workflow:
        flash("Generate headlines from the current saved articles first.", "info")
        return redirect(url_for("saved_articles.saved_articles_view"))

    items = workflow["items"]
    index = workflow["index"]
    pending_count = len({str(article.get("id")) for article in saved} - set(items))
    categories = OrderedDict(
        (
            category,
            [items[article_id] for article_id in index.get(category, []) if article_id in items],
        )
        for category in ALL_CATEGORIES
    )
    return render_template(
        "headlines/review.html",
        categories=categories,
        page_title="Main Newsletter — Finalize",
        built_at=workflow.get("built_at"),
        pending_count=pending_count,
        move_url=url_for("headlines.move"),
        rename_url=url_for("headlines.rename"),
        generate_url=url_for("headlines.generate"),
        back_url=url_for("saved_articles.saved_articles_view"),
        back_label="← Saved Articles",
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

    workflow["items"][article_id]["headline"] = headline
    workflow["built_at"] = datetime.now().isoformat(timespec="seconds")
    session["headline_workflow"] = workflow
    session.modified = True
    return jsonify(ok=True)


@headlines.post("/move")
def move():
    payload = request.get_json(silent=True) or {}
    article_id = str(payload.get("id") or "").strip()
    from_category = str(payload.get("from_category") or "").strip()
    to_category = str(payload.get("to_category") or "").strip()
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
    removed = False
    search_order = [from_category, *ALL_CATEGORIES]
    for category in dict.fromkeys(search_order):
        if category not in index:
            continue
        try:
            index[category].remove(article_id)
            removed = True
            break
        except ValueError:
            continue

    if not removed:
        return jsonify(ok=False, error="Article not found"), 404

    destination = index.setdefault(to_category, [])
    destination.insert(max(0, min(new_index, len(destination))), article_id)
    workflow["index"] = index
    workflow["built_at"] = datetime.now().isoformat(timespec="seconds")
    session["headline_workflow"] = workflow
    session.modified = True
    return jsonify(ok=True)
