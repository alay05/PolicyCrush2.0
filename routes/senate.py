from flask import Blueprint, render_template, request
from datetime import datetime, timedelta

from features.classify import classify
from routes.saved_articles import get_manual_pull, prepare_article, store_manual_pull
from sources.catalog import SENATE_SOURCES

senate = Blueprint("senate", __name__)

@senate.route("/senate", methods=["GET", "POST"])
def senate_view():
    input_date = (datetime.today() - timedelta(days=3)).strftime("%Y-%m-%d")
    start_date = None
    error = None
    committees = {}
    use_openai = False

    if request.method == "GET":
        cached = get_manual_pull("senate")
        if cached:
            input_date = cached.get("input_date", input_date)
            use_openai = bool(cached.get("use_openai", False))
            committees = cached.get("results") or {}

    if request.method == "POST":
        input_date = request.form.get("start_date", "").strip()
        use_openai = "use_openai" in request.form

        if input_date:
            try:
                start_date = datetime.strptime(input_date, "%Y-%m-%d").date()
            except ValueError:
                error = "Invalid date."

        if not error and start_date:
            cached_items = []
            for name, fetch in SENATE_SOURCES.items():
                try:
                    payload = fetch(start_date)
                    articles = payload["articles"]
                    base_url = payload["base_url"]

                    grouped = {
                        "url": base_url,
                        "majority": [],
                        "minority": [],
                        "hearing": [],
                    }

                    for article in articles:
                        if use_openai:
                            article["suggestion"] = classify(article["title"])
                        tag = article.get("tag", "")
                        if tag in grouped:
                            prepared = prepare_article(article, "senate", name, tag)
                            grouped[tag].append(prepared)
                            cached_items.append(prepared)

                    committees[name] = grouped
                except Exception as e:
                    print(f"Error loading {name}: {e}")

            store_manual_pull("senate", committees, cached_items, input_date, use_openai)

    return render_template("senate.html", committees=committees, error=error, input_date=input_date, use_openai=use_openai)
