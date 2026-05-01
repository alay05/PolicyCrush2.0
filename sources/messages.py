import base64
import email
import json
import os
import pickle
from email.header import decode_header
from email.utils import parseaddr

from flask import has_request_context, session
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow, InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly",
]
SESSION_KEY = "gmail_oauth_credentials"
STATE_KEY = "gmail_oauth_state"
REDIRECT_KEY = "gmail_post_auth_redirect"


class GmailAuthRequired(RuntimeError):
    def __init__(self, authorize_url: str):
        super().__init__("Gmail authorization required")
        self.authorize_url = authorize_url


def _allow_insecure_local_oauth(redirect_uri: str):
    if redirect_uri.startswith("http://127.0.0.1") or redirect_uri.startswith("http://localhost"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    else:
        os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)


def _oauth_client_config():
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    project_id = os.getenv("GOOGLE_OAUTH_PROJECT_ID", "").strip()

    if client_id and client_secret:
        return {
            "web": {
                "client_id": client_id,
                "project_id": project_id or "policycrush",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": client_secret,
                "redirect_uris": [],
                "javascript_origins": [],
            }
        }

    if os.path.exists("credentials.json"):
        with open("credentials.json", "r", encoding="utf-8") as fh:
            config = json.load(fh)
        if "web" in config:
            return config

    return None


def _serialize_credentials(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }


def _deserialize_credentials(payload: dict | None) -> Credentials | None:
    if not payload:
        return None

    creds = Credentials(
        token=payload.get("token"),
        refresh_token=payload.get("refresh_token"),
        token_uri=payload.get("token_uri"),
        client_id=payload.get("client_id"),
        client_secret=payload.get("client_secret"),
        scopes=payload.get("scopes") or SCOPES,
    )

    expiry = payload.get("expiry")
    if expiry:
        try:
            creds.expiry = __import__("datetime").datetime.fromisoformat(expiry)
        except ValueError:
            pass
    return creds


def is_authenticated() -> bool:
    if has_request_context():
        creds = _deserialize_credentials(session.get(SESSION_KEY))
        return bool(creds and (creds.valid or creds.refresh_token))
    return os.path.exists("token.pickle")


def start_auth_flow(redirect_uri: str, next_url: str) -> str:
    config = _oauth_client_config()
    if not config:
        raise RuntimeError(
            "Google OAuth web credentials are not configured. Set GOOGLE_OAUTH_CLIENT_ID and "
            "GOOGLE_OAUTH_CLIENT_SECRET, or provide a web credentials.json."
        )

    _allow_insecure_local_oauth(redirect_uri)
    flow = Flow.from_client_config(config, SCOPES)
    flow.redirect_uri = redirect_uri
    authorize_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    session[STATE_KEY] = state
    session[REDIRECT_KEY] = next_url
    session.modified = True
    return authorize_url


def finish_auth_flow(authorization_response: str, redirect_uri: str):
    config = _oauth_client_config()
    if not config:
        raise RuntimeError("Google OAuth web credentials are not configured.")

    state = session.get(STATE_KEY)
    if not state:
        raise RuntimeError("Missing Gmail OAuth state in session.")

    _allow_insecure_local_oauth(redirect_uri)
    flow = Flow.from_client_config(config, SCOPES, state=state)
    flow.redirect_uri = redirect_uri
    flow.fetch_token(authorization_response=authorization_response)

    session[SESSION_KEY] = _serialize_credentials(flow.credentials)
    session.pop(STATE_KEY, None)
    session.modified = True
    return session.pop(REDIRECT_KEY, None) or "/gmail"


def _authenticate_local_desktop():
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return build("gmail", "v1", credentials=creds)


def authenticate():
    if not has_request_context():
        return _authenticate_local_desktop()

    creds = _deserialize_credentials(session.get(SESSION_KEY))
    if not creds:
        raise GmailAuthRequired("/gmail/oauth/start")

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            session[SESSION_KEY] = _serialize_credentials(creds)
            session.modified = True
        else:
            raise GmailAuthRequired("/gmail/oauth/start")

    return build("gmail", "v1", credentials=creds)


def logout():
    if has_request_context():
        removed = False
        for key in (SESSION_KEY, STATE_KEY, REDIRECT_KEY):
            if key in session:
                session.pop(key, None)
                removed = True
        if removed:
            session.modified = True
        return removed

    if os.path.exists("token.pickle"):
        os.remove("token.pickle")
        return True
    return False


def get_messages(service):
    query = "is:unread"
    result = service.users().messages().list(userId="me", q=query).execute()
    return result.get("messages", [])


def extract_html_from_email(service, msg_id):
    msg = service.users().messages().get(userId="me", id=msg_id, format="raw").execute()
    msg_str = base64.urlsafe_b64decode(msg["raw"].encode("ASCII"))
    mime_msg = email.message_from_bytes(msg_str)

    service.users().messages().modify(
        userId="me",
        id=msg_id,
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()

    raw_subject = mime_msg.get("Subject", "(No Subject)")
    decoded_parts = decode_header(raw_subject)
    subject = "".join(
        [(part.decode(enc or "utf-8") if isinstance(part, bytes) else part) for part, enc in decoded_parts]
    )

    from_header = mime_msg.get("From", "")
    sender_name, sender_email = parseaddr(from_header)
    sender_display = sender_name or sender_email

    for part in mime_msg.walk():
        if part.get_content_type() == "text/html":
            html = part.get_payload(decode=True).decode(errors="replace")
            return f"FROM: {sender_display} - SUBJECT: {subject}", html

    return f"FROM: {sender_display} \n SUBJECT: {subject}", ""
