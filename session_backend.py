import asyncio
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from flask.sessions import SessionInterface, SessionMixin
from itsdangerous import BadSignature, Signer
import requests
from werkzeug.datastructures import CallbackDict


class ServerSideSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, sid=None):
        def on_update(session):
            session.modified = True

        super().__init__(initial, on_update)
        self.sid = sid
        self.modified = False


class VercelBlobSessionInterface(SessionInterface):
    session_class = ServerSideSession

    def __init__(self, secret_key: str, token: str, prefix: str = "sessions/"):
        from vercel.blob import delete as blob_delete
        from vercel.blob import get as blob_get
        from vercel.blob import put as blob_put

        self.secret_key = secret_key
        self.token = token
        self.prefix = prefix
        self._blob_get = blob_get
        self._blob_put = blob_put
        self._blob_delete = blob_delete

    def _signer(self):
        return Signer(self.secret_key, salt="policycrush-session")

    def _sign_sid(self, sid: str) -> str:
        return self._signer().sign(sid.encode("utf-8")).decode("utf-8")

    def _unsign_sid(self, value: str) -> str | None:
        if not value:
            return None
        try:
            return self._signer().unsign(value.encode("utf-8")).decode("utf-8")
        except BadSignature:
            return None

    def _blob_path(self, sid: str) -> str:
        return f"{self.prefix}{sid}.json"

    def _session_expiry(self, app, session) -> datetime:
        lifetime = app.permanent_session_lifetime or timedelta(days=7)
        if not isinstance(lifetime, timedelta):
            lifetime = timedelta(days=7)
        return datetime.now(timezone.utc) + lifetime

    async def _consume_async_stream(self, stream) -> bytes:
        chunks = []
        async for chunk in stream:
            chunks.append(chunk)
        return b"".join(chunks)

    def _read_stream(self, stream) -> bytes:
        if hasattr(stream, "__aiter__"):
            return asyncio.run(self._consume_async_stream(stream))
        return b"".join(stream)

    def _load_blob_payload(self, sid: str) -> dict | None:
        result = self._blob_get(self._blob_path(sid), access="private", token=self.token)
        if not result:
            return None

        if getattr(result, "stream", None):
            raw = self._read_stream(result.stream)
        else:
            download_url = (
                getattr(result, "url", None)
                or getattr(result, "download_url", None)
                or getattr(result, "downloadUrl", None)
            )
            if not download_url:
                return None

            response = requests.get(
                download_url,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=20,
            )
            response.raise_for_status()
            raw = response.content

        payload = json.loads(raw.decode("utf-8"))
        expires_at = payload.get("expires_at")
        if expires_at:
            expires = datetime.fromisoformat(expires_at)
            if expires <= datetime.now(timezone.utc):
                self._blob_delete(self._blob_path(sid), token=self.token)
                return None
        return payload.get("data") or {}

    def open_session(self, app, request):
        signed_sid = request.cookies.get(self.get_cookie_name(app))
        sid = self._unsign_sid(signed_sid) if signed_sid else None
        if not sid:
            return self.session_class(sid=secrets.token_urlsafe(32))

        try:
            data = self._load_blob_payload(sid)
        except Exception:
            data = None

        if data is None:
            return self.session_class(sid=secrets.token_urlsafe(32))
        return self.session_class(data, sid=sid)

    def save_session(self, app, session, response):
        cookie_name = self.get_cookie_name(app)

        if not session:
            if getattr(session, "sid", None):
                try:
                    self._blob_delete(self._blob_path(session.sid), token=self.token)
                except Exception:
                    pass
            response.delete_cookie(cookie_name, domain=self.get_cookie_domain(app), path=self.get_cookie_path(app))
            return

        expires = self.get_expiration_time(app, session)
        expiry_marker = self._session_expiry(app, session)

        payload = {
            "expires_at": expiry_marker.isoformat(),
            "data": dict(session),
        }
        self._blob_put(
            self._blob_path(session.sid),
            json.dumps(payload).encode("utf-8"),
            access="private",
            content_type="application/json",
            overwrite=True,
            token=self.token,
        )

        response.set_cookie(
            cookie_name,
            self._sign_sid(session.sid),
            expires=expires,
            httponly=self.get_cookie_httponly(app),
            secure=self.get_cookie_secure(app),
            samesite=self.get_cookie_samesite(app),
            path=self.get_cookie_path(app),
            domain=self.get_cookie_domain(app),
        )


def configure_session(app):
    blob_token = os.getenv("BLOB_READ_WRITE_TOKEN")
    if blob_token:
        app.session_interface = VercelBlobSessionInterface(
            secret_key=app.secret_key,
            token=blob_token,
        )
        return

    if os.getenv("VERCEL"):
        raise RuntimeError(
            "BLOB_READ_WRITE_TOKEN is required on Vercel so the multi-step workflow has durable session storage."
        )

    from flask_session import Session

    Session(app)
