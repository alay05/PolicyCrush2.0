import os
import tempfile


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "CHANGE_ME_TO_RANDOM_STRING")
    USE_PUBLIC_ASSETS = env_flag("USE_PUBLIC_ASSETS", env_flag("VERCEL", False))
    SESSION_COOKIE_SECURE = env_flag("SESSION_COOKIE_SECURE", env_flag("VERCEL", False))
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")

    SESSION_TYPE = os.getenv("SESSION_TYPE", "filesystem")
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    SESSION_FILE_DIR = os.getenv(
        "SESSION_FILE_DIR",
        os.path.join(tempfile.gettempdir(), "policycrush-sessions"),
    )

    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
    HEADLINE_OPENAI_MODEL = os.getenv("HEADLINE_OPENAI_MODEL", "gpt-4o-mini")
    CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY", "").strip()

    HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "30"))
    SCRAPER_BROWSER_PROVIDER = os.getenv("SCRAPER_BROWSER_PROVIDER", "auto").strip().lower()
    ENABLE_SELENIUM_FALLBACK = env_flag("ENABLE_SELENIUM_FALLBACK", False)
