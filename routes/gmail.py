from flask import Blueprint, redirect, render_template, request, url_for

from sources.messages import (
    GmailAuthRequired,
    authenticate,
    extract_html_from_email,
    finish_auth_flow,
    get_messages,
    is_authenticated,
    logout,
    start_auth_flow,
)

gmail = Blueprint("gmail", __name__)


@gmail.route("/gmail/oauth/start")
def gmail_oauth_start():
    next_url = request.args.get("next") or url_for("gmail.gmail_view")
    authorize_url = start_auth_flow(
        redirect_uri=url_for("gmail.gmail_oauth_callback", _external=True),
        next_url=next_url,
    )
    return redirect(authorize_url)


@gmail.route("/gmail/oauth/callback")
def gmail_oauth_callback():
    next_url = finish_auth_flow(
        authorization_response=request.url,
        redirect_uri=url_for("gmail.gmail_oauth_callback", _external=True),
    )
    return redirect(next_url)


@gmail.route("/gmail", methods=["GET", "POST"])
def gmail_view():
    articles = None
    error = None
    input_date = ""
    token_exists = is_authenticated()

    if request.method == "POST":
        try:
            service = authenticate()
            messages = get_messages(service)
            articles = {}

            for msg in messages:
                subject, html = extract_html_from_email(service, msg['id'])
                if html:
                    articles[subject] = {"html": html}
        except GmailAuthRequired as exc:
            return redirect(f"{exc.authorize_url}?next={url_for('gmail.gmail_view')}")
        except Exception as e:
            error = f"Error: {e}"

    return render_template("gmail.html", articles=articles, error=error, input_date=input_date, token_exists=token_exists)

@gmail.route("/gmail/logout")
def gmail_logout():
    logout()
    return redirect(url_for("gmail.gmail_view"))
