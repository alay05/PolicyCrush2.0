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


def _response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "articles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "headline": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": ALL_CATEGORIES,
                        },
                    },
                    "required": ["id", "headline", "category"],
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
        if article_id in source_by_id and headline and article_id not in generated_by_id:
            generated_by_id[article_id] = {
                "id": article_id,
                "headline": headline,
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
        "Use Events only when is_hearing is true, and always use Events for those hearings."
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
                    "schema": _response_schema(),
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
