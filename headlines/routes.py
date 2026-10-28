from collections import OrderedDict
from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from config import Config
from headlines.generator import HeadlineGenerationError, generate_headline_records
from headlines.state import ALL_CATEGORIES, get_current_workflow
from mailchimp.client import MailchimpAPIError, MailchimpClient
from mailchimp.renderer import render_main_newsletter


headlines = Blueprint("headlines", __name__, template_folder="templates")


def _workflow_categories(workflow) -> OrderedDict:
    items = workflow["items"]
    index = workflow["index"]
    return OrderedDict(
        (
            category,
            [items[article_id] for article_id in index.get(category, []) if article_id in items],
        )
        for category in ALL_CATEGORIES
    )


def _store_mailchimp_draft(workflow, draft: dict) -> None:
    workflow["mailchimp_draft"] = draft
    session["headline_workflow"] = workflow
    session.modified = True


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
        rename_url=url_for("headlines.rename"),
        generate_url=url_for("headlines.generate"),
        back_url=url_for("saved_articles.saved_articles_view"),
        back_label="← Saved Articles",
        mailchimp_enabled=True,
        mailchimp_configured=bool(Config.MAILCHIMP_API_KEY),
        mailchimp_draft=mailchimp_draft,
        mailchimp_stale=(
            bool(mailchimp_draft)
            and mailchimp_draft.get("content_hash") != content_hash
        ),
        mailchimp_action_url=url_for("headlines.mailchimp_draft"),
    )


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
    html, content_hash = render_main_newsletter(categories)
    draft = dict(workflow.get("mailchimp_draft") or {})

    try:
        client = MailchimpClient()
    except MailchimpAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("headlines.review"))

    campaign_id = str(draft.get("campaign_id") or "")
    create_replacement = request.form.get("create_replacement") == "1"
    if draft.get("unavailable") and not create_replacement:
        flash("The previous Mailchimp draft is unavailable. Confirm creation of a replacement.", "error")
        return redirect(url_for("headlines.review"))

    if campaign_id and not draft.get("unavailable"):
        if draft.get("content_hash") != content_hash and request.form.get("confirm") != "1":
            flash("Confirm before overwriting the existing Mailchimp draft.", "error")
            return redirect(url_for("headlines.review"))
        try:
            campaign = client.get_campaign(campaign_id)
        except MailchimpAPIError as exc:
            if exc.status_code == 404:
                draft["unavailable"] = True
                draft["unavailable_reason"] = "The campaign no longer exists in Mailchimp."
                _store_mailchimp_draft(workflow, draft)
                flash(draft["unavailable_reason"], "error")
                return redirect(url_for("headlines.review"))
            flash(str(exc), "error")
            return redirect(url_for("headlines.review"))

        if campaign.get("status") != "save":
            draft["unavailable"] = True
            draft["unavailable_reason"] = "The campaign is no longer an editable saved draft."
            _store_mailchimp_draft(workflow, draft)
            flash(draft["unavailable_reason"], "error")
            return redirect(url_for("headlines.review"))
    else:
        try:
            campaign = client.create_campaign()
        except MailchimpAPIError as exc:
            flash(str(exc), "error")
            return redirect(url_for("headlines.review"))

        campaign_id = str(campaign.get("id") or "")
        if not campaign_id:
            flash("Mailchimp created a campaign without returning its ID.", "error")
            return redirect(url_for("headlines.review"))
        web_id = campaign.get("web_id")
        draft = {
            "campaign_id": campaign_id,
            "web_id": web_id,
            "editor_url": client.editor_url(web_id) if web_id is not None else "",
            "content_hash": "",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "incomplete": True,
        }
        _store_mailchimp_draft(workflow, draft)

    try:
        client.set_campaign_content(campaign_id, html)
    except MailchimpAPIError as exc:
        draft["incomplete"] = True
        _store_mailchimp_draft(workflow, draft)
        flash(f"The Mailchimp draft was created, but its content could not be uploaded: {exc}", "error")
        return redirect(url_for("headlines.review"))

    draft.update(
        content_hash=content_hash,
        incomplete=False,
        unavailable=False,
        updated_at=datetime.now().isoformat(timespec="seconds"),
    )
    draft.pop("unavailable_reason", None)
    _store_mailchimp_draft(workflow, draft)
    flash("Mailchimp draft created successfully.", "success")
    if draft.get("editor_url"):
        return redirect(draft["editor_url"])
    return redirect(url_for("headlines.review"))


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
