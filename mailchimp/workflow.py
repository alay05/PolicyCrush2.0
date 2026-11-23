"""Shared editable Mailchimp draft lifecycle for newsletter workflows."""
from datetime import datetime

from flask import flash, redirect, request, session, url_for

from config import Config
from mailchimp.client import MailchimpAPIError, MailchimpClient


def _store_mailchimp_draft(workflow, draft: dict, session_key: str) -> None:
    workflow["mailchimp_draft"] = draft
    session[session_key] = workflow
    session.modified = True


def mailchimp_draft_stale(draft: dict, content_hash: str) -> bool:
    return bool(draft) and (
        draft.get("content_hash") != content_hash
        or draft.get("template_id") != Config.MAILCHIMP_TEMPLATE_ID
    )


def create_or_update_draft(
    workflow, *, session_key: str, review_endpoint: str,
    content_hash: str, sections: dict[str, str], client_factory=MailchimpClient,
):
    """Create a template draft, or safely reuse/update this workflow's draft."""
    draft = dict(workflow.get("mailchimp_draft") or {})

    try:
        client = client_factory()
    except MailchimpAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for(review_endpoint))

    campaign_id = str(draft.get("campaign_id") or "")
    create_replacement = request.form.get("create_replacement") == "1"
    if draft.get("unavailable") and not create_replacement:
        flash("The previous Mailchimp draft is unavailable. Confirm creation of a replacement.", "error")
        return redirect(url_for(review_endpoint))

    if campaign_id and not draft.get("unavailable"):
        if mailchimp_draft_stale(draft, content_hash) and request.form.get("confirm") != "1":
            flash("Confirm before overwriting the existing Mailchimp draft.", "error")
            return redirect(url_for(review_endpoint))
        try:
            campaign = client.get_campaign(campaign_id)
        except MailchimpAPIError as exc:
            if exc.status_code == 404:
                draft["unavailable"] = True
                draft["unavailable_reason"] = "The campaign no longer exists in Mailchimp."
                _store_mailchimp_draft(workflow, draft, session_key)
                flash(draft["unavailable_reason"], "error")
                return redirect(url_for(review_endpoint))
            flash(str(exc), "error")
            return redirect(url_for(review_endpoint))

        if campaign.get("status") != "save":
            draft["unavailable"] = True
            draft["unavailable_reason"] = "The campaign is no longer an editable saved draft."
            _store_mailchimp_draft(workflow, draft, session_key)
            flash(draft["unavailable_reason"], "error")
            return redirect(url_for(review_endpoint))
        if not mailchimp_draft_stale(draft, content_hash) and not draft.get("incomplete"):
            return redirect(draft.get("editor_url") or url_for(review_endpoint))
        try:
            client.validate_template()
        except MailchimpAPIError as exc:
            flash(str(exc), "error")
            return redirect(url_for(review_endpoint))
    else:
        try:
            client.validate_template()
            campaign = client.create_campaign()
        except MailchimpAPIError as exc:
            flash(str(exc), "error")
            return redirect(url_for(review_endpoint))

        campaign_id = str(campaign.get("id") or "")
        if not campaign_id:
            flash("Mailchimp created a campaign without returning its ID.", "error")
            return redirect(url_for(review_endpoint))
        web_id = campaign.get("web_id")
        draft = {
            "campaign_id": campaign_id,
            "web_id": web_id,
            "editor_url": client.editor_url(web_id) if web_id is not None else "",
            "content_hash": "",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "incomplete": True,
        }
        _store_mailchimp_draft(workflow, draft, session_key)

    try:
        client.set_campaign_content(campaign_id, sections)
    except MailchimpAPIError as exc:
        draft["incomplete"] = True
        _store_mailchimp_draft(workflow, draft, session_key)
        flash(f"The Mailchimp draft was created, but its content could not be uploaded: {exc}", "error")
        return redirect(url_for(review_endpoint))

    draft.update(
        content_hash=content_hash,
        template_id=Config.MAILCHIMP_TEMPLATE_ID,
        incomplete=False,
        unavailable=False,
        updated_at=datetime.now().isoformat(timespec="seconds"),
    )
    draft.pop("unavailable_reason", None)
    _store_mailchimp_draft(workflow, draft, session_key)
    flash("Mailchimp draft created successfully.", "success")
    if draft.get("editor_url"):
        return redirect(draft["editor_url"])
    return redirect(url_for(review_endpoint))


