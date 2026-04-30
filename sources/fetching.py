from contextlib import suppress

import requests
from bs4 import BeautifulSoup

from config import Config

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )
}


class ScraperUnavailableError(RuntimeError):
    pass


def fetch_html(url: str, headers=None, timeout=None) -> str:
    request_headers = dict(DEFAULT_HEADERS)
    if headers:
        request_headers.update(headers)

    response = requests.get(
        url,
        headers=request_headers,
        timeout=timeout or Config.HTTP_TIMEOUT_SECONDS,
    )
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
