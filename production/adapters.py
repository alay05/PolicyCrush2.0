import hashlib
from datetime import datetime, date, timedelta
from features.classify import classify

from sources.messages import GmailAuthRequired, authenticate, get_messages, extract_html_from_email
from sources.catalog import HOUSE_SOURCES, NEWS_SOURCES, SENATE_SOURCES
from sources.house.hearings import fetch_house_hearings
from sources.senate.hearings import fetch_senate_hearings


def fetch_gmail_unread():
    service = authenticate()
    messages = get_messages(service)
    out = []
    for msg in messages:
        subject, html = extract_html_from_email(service, msg["id"])
        if html:
            out.append({
                "id": msg["id"],
                "title": subject or "(no subject)",
                "url": "",
                "date": "",
                "html": html,
                "source": "gmail",
            })
    return out

def _shift_back_one_day(d):
    try:
        if isinstance(d, datetime):
            return d - timedelta(days=1)
        if isinstance(d, date):
            return d - timedelta(days=1)
        if isinstance(d, str) and d:
            # try ISO first
            try:
                dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
                newdatetime = dt - timedelta(days=1)
                # preserve datetime vs date-like string
                if "T" in d or ":" in d:
                    return newdatetime.isoformat()
                return newdatetime.date().isoformat()
            except ValueError:
                # fallback: YYYY-MM-DD
                dt = datetime.strptime(d, "%Y-%m-%d")
                return (dt.date() - timedelta(days=1)).isoformat()
    except Exception:
        pass
    return d

def _aid(url: str, source: str) -> str:
    return hashlib.sha1(f"{source}|{url}".encode("utf-8")).hexdigest()[:16]

def fetch_news_bundle(start_date: datetime.date, use_openai: bool = False):
    out = {}
    failures = []
    for name, fetch in NEWS_SOURCES.items():
        try:
            payload = fetch(start_date)
            items = []
            for art in payload.get("articles", []):
                date_val = art.get("date", "")
                if name == "Congress" and date_val:               
                    date_val = _shift_back_one_day(date_val)
                item = {
                    "id": _aid(art["url"], name),
                    "title": art["title"],
                    "url": art["url"],
                    "date": date_val,
                    "source": name,
                }
                if "suggestion" in art and art["suggestion"]:
                    item["suggestion"] = art["suggestion"]
                elif use_openai:
                    item["suggestion"] = classify(item["title"])
                items.append(item)
            out[name] = {"url": payload.get("url", ""), "items": items}
        except Exception as exc:
            failures.append({"source": name, "error": str(exc)})
            continue
    for name, fetch in NEWS_SOURCES.items():
        out.setdefault(name, {"url": "", "items": []})
    return out, failures

def _hid(url: str, committee: str, side: str) -> str:
    return hashlib.sha1(f"{committee}|{side}|{url}".encode("utf-8")).hexdigest()[:16]

def fetch_house_bundle(start_date: datetime.date, use_openai: bool = False):
    out = {}
    try:
        hearing_results = fetch_house_hearings(start_date)
    except Exception:
        hearing_results = {}

    for committee, fns in HOUSE_SOURCES.items():
        try:
            maj = fns["majority"](start_date)
            mino = fns["minority"](start_date)

            def norm(items, side):
                res = []
                for a in items:
                    item = {
                        "id": _hid(a["url"], committee, side),
                        "title": a["title"],
                        "url": a["url"],
                        "date": a.get("date", ""),
                        "committee": committee,
                        "side": side,
                        "tag": side,
                    }
                    if "suggestion" in a and a["suggestion"]:
                        item["suggestion"] = a["suggestion"]
                    elif use_openai:
                        item["suggestion"] = classify(item["title"])
                    res.append(item)
                return res

            out[committee] = {
                "majority": norm(maj, "majority"),
                "minority": norm(mino, "minority"),
                "hearing": norm(hearing_results.get(committee, []), "hearing"),
            }
        except Exception:
            continue
    return out

def _sid(url: str, committee: str, tag: str) -> str:
    return hashlib.sha1(f"{committee}|{tag}|{url}".encode("utf-8")).hexdigest()[:16]

def fetch_senate_bundle(start_date: datetime.date, use_openai: bool = False):
    out = {}
    try:
        hearing_results = fetch_senate_hearings(start_date)
    except Exception:
        hearing_results = {}

    for name, fetch in SENATE_SOURCES.items():
        try:
            payload = fetch(start_date)  # {"articles":[{title,url,date,tag?}], "base_url": "..."}
            base_url = payload.get("base_url", "")
            majority, minority, hearing = [], [], []

            for art in payload.get("articles", []):
                tag = art.get("tag", "")
                item = {
                    "id": _sid(art["url"], name, tag or "article"),
                    "title": art["title"],
                    "url": art["url"],
                    "date": art["date"].isoformat() if isinstance(art.get("date"), (date, datetime)) else art.get("date", ""),
                    "committee": name,
                    "tag": tag or "article",
                }
                if "suggestion" in art and art["suggestion"]:
                    item["suggestion"] = art["suggestion"]
                elif use_openai:
                    item["suggestion"] = classify(item["title"])

                if tag == "majority":
                    majority.append(item)
                elif tag == "minority":
                    minority.append(item)
                elif tag == "hearing":
                    hearing.append(item)
                else:
                    majority.append(item)

            for art in hearing_results.get(name, []):
                item = {
                    "id": _sid(art["url"], name, "hearing"),
                    "title": art["title"],
                    "url": art["url"],
                    "date": art["date"].isoformat() if isinstance(art.get("date"), (date, datetime)) else art.get("date", ""),
                    "committee": name,
                    "tag": "hearing",
                }
                if use_openai:
                    item["suggestion"] = classify(item["title"])
                hearing.append(item)

            out[name] = {"url": base_url, "majority": majority, "minority": minority, "hearing": hearing}
        except Exception:
            continue
    return out
