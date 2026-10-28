from __future__ import annotations

import re

import requests

from config import Config


class MailchimpAPIError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class MailchimpClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key if api_key is not None else Config.MAILCHIMP_API_KEY).strip()
        if not self.api_key:
            raise MailchimpAPIError("MAILCHIMP_API_KEY is not configured.")

        separator, data_center = self.api_key.rpartition("-")[1:]
        if not separator or not re.fullmatch(r"[a-zA-Z0-9]+", data_center):
            raise MailchimpAPIError("MAILCHIMP_API_KEY does not include a valid data center suffix.")
        self.data_center = data_center.lower()
        self.base_url = f"https://{self.data_center}.api.mailchimp.com/3.0"

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=Config.HTTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise MailchimpAPIError(f"Couldn't reach Mailchimp: {exc}") from exc

        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}
        if not response.ok:
            detail = data.get("detail") or data.get("title") or response.reason
            raise MailchimpAPIError(
                f"Mailchimp request failed: {detail}",
                status_code=response.status_code,
            )
        return data

    def create_campaign(self) -> dict:
        return self._request("POST", "/campaigns", {"type": "regular"})

    def get_campaign(self, campaign_id: str) -> dict:
        return self._request("GET", f"/campaigns/{campaign_id}")

    def set_campaign_content(self, campaign_id: str, html: str) -> dict:
        return self._request("PUT", f"/campaigns/{campaign_id}/content", {"html": html})

    def editor_url(self, web_id) -> str:
        return f"https://{self.data_center}.admin.mailchimp.com/campaigns/show/?id={web_id}"
