from flask import session

from features.categorize import CATEGORIES, SPECIAL_CALENDAR


ALL_CATEGORIES = [SPECIAL_CALENDAR, *CATEGORIES]


def get_current_workflow(saved_articles: list[dict] | None = None):
    saved_articles = list(saved_articles if saved_articles is not None else session.get("saved_articles") or [])
    saved_ids = {str(article.get("id")) for article in saved_articles}
    workflow = session.get("headline_workflow") or {}
    raw_items = workflow.get("items")
    raw_index = workflow.get("index")
    if not saved_ids or not isinstance(raw_items, dict) or not isinstance(raw_index, dict):
        return None

    items = {
        article_id: item
        for article_id, item in raw_items.items()
        if article_id in saved_ids
    }
    if not items:
        return None

    index = {category: [] for category in ALL_CATEGORIES}
    placed = set()
    for category in ALL_CATEGORIES:
        for article_id in raw_index.get(category, []):
            if article_id in items and article_id not in placed:
                index[category].append(article_id)
                placed.add(article_id)

    for article_id in items:
        if article_id not in placed:
            index["Quality and Innovation"].append(article_id)

    if items != raw_items or index != raw_index or "source_signature" in workflow:
        workflow["items"] = items
        workflow["index"] = index
        workflow.pop("source_signature", None)
        session["headline_workflow"] = workflow
        session.modified = True
    return workflow


def get_headline_status(saved_articles: list[dict]) -> tuple[int, int]:
    workflow = get_current_workflow(saved_articles)
    generated_ids = set(workflow["items"]) if workflow else set()
    saved_ids = {str(article.get("id")) for article in saved_articles}
    return len(generated_ids & saved_ids), len(saved_ids - generated_ids)


def remove_article_from_workflow(article_id: str) -> None:
    workflow = session.get("headline_workflow") or {}
    items = workflow.get("items")
    index = workflow.get("index")
    if not isinstance(items, dict) or not isinstance(index, dict):
        return

    items.pop(article_id, None)
    for category in list(index):
        index[category] = [item_id for item_id in index[category] if item_id != article_id]

    if items:
        workflow["items"] = items
        workflow["index"] = index
        workflow.pop("source_signature", None)
        session["headline_workflow"] = workflow
    else:
        session.pop("headline_workflow", None)
    session.modified = True


def clear_workflow() -> None:
    session.pop("headline_workflow", None)
