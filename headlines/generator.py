import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from config import Config
from features.categorize import CATEGORIES, SPECIAL_CALENDAR


HEADLINES_FILE = Path(__file__).with_name("headlines.txt")
ALL_CATEGORIES = [SPECIAL_CALENDAR, *CATEGORIES]


class HeadlineGenerationError(RuntimeError):
    pass


def load_style_examples() -> list[str]:
    return [
        line.strip()
        for line in HEADLINES_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _response_schema(
    allowed_categories: list[str] | None = None,
    include_link_text: bool = False,
) -> dict:
    allowed_categories = allowed_categories or ALL_CATEGORIES
    properties = {
        "id": {"type": "string"},
        "headline": {"type": "string"},
        "category": {
            "type": "string",
            "enum": allowed_categories,
        },
    }
    required = ["id", "headline", "category"]
    if include_link_text:
        properties["link_text"] = {"type": "string"}
        required.append("link_text")
    return {
        "type": "object",
        "properties": {
            "articles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            }
        },
        "required": ["articles"],
        "additionalProperties": False,
    }


def _normalize_results(articles: list[dict], generated: list[dict]) -> list[dict]:
    source_by_id = {str(article.get("id")): article for article in articles}
    generated_by_id = {}

    for result in generated:
        article_id = str(result.get("id") or "").strip()
        headline = str(result.get("headline") or "").strip()
        category = str(result.get("category") or "").strip()
        link_text = str(result.get("link_text") or "").strip()
        if not link_text or link_text not in headline:
            link_text = headline
        if article_id in source_by_id and headline and article_id not in generated_by_id:
            generated_by_id[article_id] = {
                "id": article_id,
                "headline": headline,
                "link_text": link_text,
                "category": category,
            }

    missing = [article_id for article_id in source_by_id if article_id not in generated_by_id]
    if missing:
        raise HeadlineGenerationError("OpenAI did not return a headline for every saved article.")

    normalized = []
    for article in articles:
        result = generated_by_id[str(article.get("id"))]
        is_hearing = article.get("section") == "hearing"
        if is_hearing:
            result["category"] = SPECIAL_CALENDAR
        elif result["category"] not in CATEGORIES:
            result["category"] = "Quality and Innovation"
        normalized.append(result)
    return normalized


def generate_headline_records(articles: list[dict]) -> list[dict]:
    if not articles:
        return []

    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HeadlineGenerationError("OPENAI_API_KEY is not set.")

    style_examples = load_style_examples()
    source_articles = [
        {
            "id": str(article.get("id") or ""),
            "original_headline": str(article.get("title") or ""),
            "source": str(article.get("source_label") or ""),
            "is_hearing": article.get("section") == "hearing",
        }
        for article in articles
    ]

    instructions = (
        "You edit headlines for a concise U.S. healthcare policy newsletter. "
        "Rewrite every supplied original headline in the style demonstrated by the examples. "
        "Preserve factual meaning, names, party/state/district identifiers, bill numbers, agencies, "
        "program names, dollar amounts, and other material specifics. Do not invent facts. "
        "Use title case and return each input ID exactly once. Assign exactly one allowed category. "
        "Use Events only when is_hearing is true, and always use Events for those hearings. "
        "For link_text, return the exact contiguous action word or short action phrase within the "
        "generated headline that should link to the source, such as Announces, Releases, or "
        "Issues Guidance."
    )
    prompt = (
        "STYLE EXAMPLES:\n"
        + "\n".join(f"- {headline}" for headline in style_examples)
        + "\n\nALLOWED CATEGORIES:\n"
        + "\n".join(f"- {category}" for category in ALL_CATEGORIES)
        + "\n\nARTICLES TO PROCESS:\n"
        + json.dumps(source_articles, ensure_ascii=False)
    )

    try:
        response = OpenAI(api_key=api_key).responses.create(
            model=Config.HEADLINE_OPENAI_MODEL,
            instructions=instructions,
            input=prompt,
            temperature=0.2,
            store=False,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "generated_headlines",
                    "strict": True,
                    "schema": _response_schema(include_link_text=True),
                }
            },
        )
        payload = json.loads(response.output_text)
        generated = payload.get("articles")
        if not isinstance(generated, list):
            raise HeadlineGenerationError("OpenAI returned an invalid headline response.")
        return _normalize_results(articles, generated)
    except HeadlineGenerationError:
        raise
    except Exception as exc:
        raise HeadlineGenerationError(f"Headline generation failed: {exc}") from exc


def _event_schedule(event: dict) -> str:
    date_label = str(event.get("date_label") or "").strip()
    time_label = str(event.get("time_label") or "").strip()
    if date_label and time_label:
        return f"{date_label} · {time_label}"
    return date_label or time_label


def generate_event_headline_records(events: list[dict]) -> list[dict]:
    """Generate simple W2W4 headlines and subject-matter categories."""
    if not events:
        return []

    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HeadlineGenerationError("OPENAI_API_KEY is not set.")

    source_events = [
        {
            "id": str(event.get("id") or ""),
            "original_title": str(event.get("title") or ""),
            "date": str(event.get("date_label") or event.get("date") or ""),
            "time": str(event.get("time_label") or ""),
            "location": str(event.get("location") or ""),
        }
        for event in events
    ]
    instructions = (
        "You write simple, literal headlines for the What to Watch For section of a U.S. "
        "healthcare policy newsletter. State what each hearing, briefing, meeting, or other "
        "event is, including the responsible committee or agency and the subject when supplied. "
        "Avoid flourish, analysis, and news-style framing. Preserve factual meaning and official "
        "names, and do not invent facts. Do not put the date, time, or location in the generated "
        "headline because the application appends the exact schedule. Use title case, return every "
        "input ID exactly once, and assign exactly one allowed subject-matter category."
    )
    prompt = (
        "ALLOWED CATEGORIES:\n"
        + "\n".join(f"- {category}" for category in CATEGORIES)
        + "\n\nEVENTS TO PROCESS:\n"
        + json.dumps(source_events, ensure_ascii=False)
    )

    try:
        response = OpenAI(api_key=api_key).responses.create(
            model=Config.HEADLINE_OPENAI_MODEL,
            instructions=instructions,
            input=prompt,
            temperature=0.1,
            store=False,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "generated_event_headlines",
                    "strict": True,
                    "schema": _response_schema(CATEGORIES),
                }
            },
        )
        payload = json.loads(response.output_text)
        generated = payload.get("articles")
        if not isinstance(generated, list):
            raise HeadlineGenerationError("OpenAI returned an invalid headline response.")

        source_by_id = {str(event.get("id")): event for event in events}
        generated_by_id = {}
        for result in generated:
            event_id = str(result.get("id") or "").strip()
            headline = str(result.get("headline") or "").strip()
            category = str(result.get("category") or "").strip()
            if event_id not in source_by_id or not headline or event_id in generated_by_id:
                continue
            schedule = _event_schedule(source_by_id[event_id])
            generated_by_id[event_id] = {
                "id": event_id,
                "headline": f"{headline} — {schedule}" if schedule else headline,
                "category": category if category in CATEGORIES else "Quality and Innovation",
            }

        missing = [event_id for event_id in source_by_id if event_id not in generated_by_id]
        if missing:
            raise HeadlineGenerationError("OpenAI did not return a headline for every event.")
        return [generated_by_id[str(event.get("id"))] for event in events]
    except HeadlineGenerationError:
        raise
    except Exception as exc:
        raise HeadlineGenerationError(f"Headline generation failed: {exc}") from exc
