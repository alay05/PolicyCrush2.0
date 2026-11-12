from contextlib import suppress
import threading
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import Config

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )
}
_TRANSPORT_SEMAPHORE = threading.Semaphore(1)
_TRANSPORT_STATE_LOCK = threading.Lock()
_TRANSPORT_BLOCKED_UNTIL = {}


class ScraperUnavailableError(RuntimeError):
    pass


def _transport_group(url):
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.endswith(".senate.gov"):
        return "senate.gov"
    if hostname.endswith(".house.gov"):
        return "house.gov"
    return hostname


def _unavailable_response(url, status_code=503):
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    return response


def fetch_response(url: str, headers=None, timeout=None, *, proxy_on_block=False):
    """Fetch a page directly, optionally retrying access denials via ScrapingBee.

    ScrapingBee is only a transport here: the requested URL and returned content
    still come from the government website. Its API key is sent in a header so
    request errors and logs cannot expose it in a URL.
    """
    request_headers = dict(DEFAULT_HEADERS)
    if headers:
        request_headers.update(headers)
    request_timeout = timeout or Config.HTTP_TIMEOUT_SECONDS

    try:
        response = requests.get(url, headers=request_headers, timeout=request_timeout)
    except requests.RequestException:
        if not proxy_on_block or not Config.SCRAPINGBEE_API_KEY:
            raise
        response = None

    if not proxy_on_block or not Config.SCRAPINGBEE_API_KEY:
        return response
    if response is not None and response.status_code not in {401, 403, 429}:
        return response

    transport_group = _transport_group(url)
    with _TRANSPORT_SEMAPHORE:
        with _TRANSPORT_STATE_LOCK:
            blocked_until = _TRANSPORT_BLOCKED_UNTIL.get(transport_group, 0)
        if blocked_until > time.monotonic():
            return response if response is not None else _unavailable_response(url)

        try:
            proxy_response = requests.get(
                "https://app.scrapingbee.com/api/v1",
                params={
                    "url": url,
                    "render_js": "false",
                    "premium_proxy": str(Config.SCRAPINGBEE_PREMIUM_PROXY).lower(),
                    "country_code": "us",
                    "transparent_status_code": "true",
                },
                headers={"Authorization": f"Bearer {Config.SCRAPINGBEE_API_KEY}"},
                timeout=max(float(request_timeout), 60),
            )
        except requests.RequestException as exc:
            raise ScraperUnavailableError(
                f"The direct request was blocked and the configured scraping transport "
                f"could not load {url}."
            ) from exc

        target_denied = (
            proxy_response.status_code == 403
            and (
                proxy_response.headers.get("Spb-initial-status-code") == "403"
                or "access denied" in proxy_response.text[:1000].lower()
            )
        )
        if target_denied:
            with _TRANSPORT_STATE_LOCK:
                _TRANSPORT_BLOCKED_UNTIL[transport_group] = (
                    time.monotonic() + Config.SCRAPINGBEE_CIRCUIT_BREAKER_SECONDS
                )

    # Consumers need the government URL for relative links and pagination, not
    # the transport provider endpoint.
    proxy_response.url = url
    return proxy_response


def fetch_html(url: str, headers=None, timeout=None) -> str:
    response = fetch_response(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def fetch_page_html(url: str, wait_for_selector: str | None = None, timeout_seconds: int = 30) -> str:
    provider = Config.SCRAPER_BROWSER_PROVIDER
    errors = []

    # Most of these sources are public pages and often work without a browser.
    if provider in {"auto", "requests"}:
        with suppress(Exception):
            html = fetch_html(url, timeout=timeout_seconds)
            if not wait_for_selector:
                return html
            if BeautifulSoup(html, "html.parser").select_one(wait_for_selector):
                return html
            errors.append("requests: expected selector was not present in the HTML response")

    if provider in {"auto", "playwright"}:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(user_agent=DEFAULT_HEADERS["User-Agent"])
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
                    if wait_for_selector:
                        page.wait_for_selector(wait_for_selector, timeout=timeout_seconds * 1000)
                    return page.content()
                finally:
                    browser.close()
        except Exception as exc:
            errors.append(f"playwright: {exc}")

    if provider in {"auto", "selenium"} and Config.ENABLE_SELENIUM_FALLBACK:
        try:
            from selenium import webdriver

            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument(f"--user-agent={DEFAULT_HEADERS['User-Agent']}")

            driver = webdriver.Chrome(options=options)
            try:
                driver.set_page_load_timeout(timeout_seconds)
                driver.get(url)
                return driver.page_source
            finally:
                driver.quit()
        except Exception as exc:
            errors.append(f"selenium: {exc}")

    raise ScraperUnavailableError(
        f"Could not load browser-backed page for {url}. "
        f"Tried provider={provider}. Details: {'; '.join(errors) or 'requests-only fetch failed'}"
    )
