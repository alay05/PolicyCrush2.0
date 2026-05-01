import base64
import asyncio
import email
import json
import os
import pickle
import secrets
from email.header import decode_header
from email.utils import parseaddr

from flask import after_this_request, has_request_context, request, session
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow, InstalledAppFlow
from itsdangerous import BadSignature, Signer, URLSafeSerializer

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly",
]
SESSION_KEY = "gmail_oauth_credentials"
GMAIL_AUTH_COOKIE = "gmail_auth"


class GmailAuthRequired(RuntimeError):
    def __init__(self, authorize_url: str):
        super().__init__("Gmail authorization required")
        self.authorize_url = authorize_url


def _allow_insecure_local_oauth(redirect_uri: str):
    if redirect_uri.startswith("http://127.0.0.1") or redirect_uri.startswith("http://localhost"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    else:
        os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)


def _state_serializer() -> URLSafeSerializer:
    secret_key = os.getenv("FLASK_SECRET_KEY", "CHANGE_ME_TO_RANDOM_STRING")
    return URLSafeSerializer(secret_key, salt="gmail-oauth-state")


def _gmail_cookie_signer() -> Signer:
    secret_key = os.getenv("FLASK_SECRET_KEY", "CHANGE_ME_TO_RANDOM_STRING")
    return Signer(secret_key, salt="gmail-auth-cookie")


def _sign_gmail_sid(sid: str) -> str:
    return _gmail_cookie_signer().sign(sid.encode("utf-8")).decode("utf-8")


def _unsign_gmail_sid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _gmail_cookie_signer().unsign(value.encode("utf-8")).decode("utf-8")
    except BadSignature:
        return None


def _use_blob_auth() -> bool:
    return has_request_context() and bool(os.getenv("BLOB_READ_WRITE_TOKEN"))


def _gmail_blob_path(sid: str) -> str:
    return f"gmail-auth/{sid}.json"


async def _consume_async_stream(stream) -> bytes:
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return b"".join(chunks)


def _read_stream(stream) -> bytes:
    if hasattr(stream, "__aiter__"):
        return asyncio.run(_consume_async_stream(stream))
    return b"".join(stream)


def _load_blob_credentials_payload() -> dict | None:
    sid = _unsign_gmail_sid(request.cookies.get(GMAIL_AUTH_COOKIE))
    if not sid:
        return None

    try:
        from vercel.blob import get as blob_get

        result = blob_get(_gmail_blob_path(sid), access="private", token=os.getenv("BLOB_READ_WRITE_TOKEN"))
        if not result:
            return None

        raw = None
        if getattr(result, "stream", None):
            raw = _read_stream(result.stream)
        else:
            download_url = (
                getattr(result, "url", None)
                or getattr(result, "download_url", None)
                or getattr(result, "downloadUrl", None)
            )
            if not download_url:
                return None

            headers = {}
            blob_token = os.getenv("BLOB_READ_WRITE_TOKEN")
            if blob_token:
                headers["Authorization"] = f"Bearer {blob_token}"

            response = __import__("requests").get(download_url, headers=headers, timeout=20)
            response.raise_for_status()
            raw = response.content

        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict) and "data" in payload:
            return payload.get("data") or {}
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None
    return None


def _persist_blob_credentials(payload: dict):
    sid = _unsign_gmail_sid(request.cookies.get(GMAIL_AUTH_COOKIE)) or secrets.token_urlsafe(24)

    @after_this_request
    def _save(response):
        from vercel.blob import put as blob_put

        wrapped_payload = {"data": payload}
        blob_put(
            _gmail_blob_path(sid),
            json.dumps(wrapped_payload).encode("utf-8"),
            access="private",
            content_type="application/json",
            overwrite=True,
            token=os.getenv("BLOB_READ_WRITE_TOKEN"),
        )
        response.set_cookie(
            GMAIL_AUTH_COOKIE,
            _sign_gmail_sid(sid),
            httponly=True,
            secure=os.getenv("VERCEL", "").lower() in {"1", "true"},
            samesite=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
            path="/",
        )
        return response


def _clear_blob_credentials():
    sid = _unsign_gmail_sid(request.cookies.get(GMAIL_AUTH_COOKIE))

    @after_this_request
    def _clear(response):
        if sid:
            try:
                from vercel.blob import delete as blob_delete

                blob_delete(_gmail_blob_path(sid), token=os.getenv("BLOB_READ_WRITE_TOKEN"))
            except Exception:
                pass
        response.delete_cookie(GMAIL_AUTH_COOKIE, path="/")
        return response


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
        payload = _load_blob_credentials_payload() if _use_blob_auth() else session.get(SESSION_KEY)
        creds = _deserialize_credentials(payload)
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
    state_token = _state_serializer().dumps({"next": next_url})
    authorize_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state_token,
    )
    return authorize_url


def finish_auth_flow(authorization_response: str, redirect_uri: str):
    config = _oauth_client_config()
    if not config:
        raise RuntimeError("Google OAuth web credentials are not configured.")

    from urllib.parse import parse_qs, urlparse

    query_params = parse_qs(urlparse(authorization_response).query)
    state = (query_params.get("state") or [None])[0]
    if not state:
        raise RuntimeError("Missing Gmail OAuth state in callback.")

    try:
        state_payload = _state_serializer().loads(state)
    except BadSignature as exc:
        raise RuntimeError("Invalid Gmail OAuth state.") from exc

    _allow_insecure_local_oauth(redirect_uri)
    flow = Flow.from_client_config(config, SCOPES, state=state)
    flow.redirect_uri = redirect_uri
    flow.fetch_token(authorization_response=authorization_response)

    payload = _serialize_credentials(flow.credentials)
    if _use_blob_auth():
        _persist_blob_credentials(payload)
    else:
        session[SESSION_KEY] = payload
        session.modified = True
    return state_payload.get("next") or "/gmail"


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

    payload = _load_blob_credentials_payload() if _use_blob_auth() else session.get(SESSION_KEY)
    creds = _deserialize_credentials(payload)
    if not creds:
        raise GmailAuthRequired("/gmail/oauth/start")

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            refreshed_payload = _serialize_credentials(creds)
            if _use_blob_auth():
                _persist_blob_credentials(refreshed_payload)
            else:
                session[SESSION_KEY] = refreshed_payload
                session.modified = True
        else:
            raise GmailAuthRequired("/gmail/oauth/start")

    return build("gmail", "v1", credentials=creds)


def logout():
    if has_request_context():
        if _use_blob_auth():
            had_cookie = bool(_unsign_gmail_sid(request.cookies.get(GMAIL_AUTH_COOKIE)))
            _clear_blob_credentials()
            return had_cookie

        removed = False
        if SESSION_KEY in session:
            session.pop(SESSION_KEY, None)
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
