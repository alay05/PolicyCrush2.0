from flask import Blueprint, render_template, request
from datetime import datetime, timedelta

from features.classify import classify
from routes.saved_articles import get_manual_pull, prepare_article, store_manual_pull
from sources.catalog import HOUSE_SOURCES

house = Blueprint("house", __name__)

@house.route("/house", methods=["GET", "POST"])
def house_view():
    input_date = (datetime.today() - timedelta(days=3)).strftime("%Y-%m-%d")
    start_date = None
    error = None
    committees = {}
    use_openai = False

    if request.method == "GET":
        cached = get_manual_pull("house")
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
            for name, fetch in HOUSE_SOURCES.items():
                try:
                    maj_articles = fetch["majority"](start_date)
                    min_articles = fetch["minority"](start_date)

                    if use_openai:
                        for article in maj_articles:
                            article["suggestion"] = classify(article["title"])
                        for article in min_articles:
                            article["suggestion"] = classify(article["title"])

                    majority = [
                        prepare_article(article, "house", name, "majority")
                        for article in maj_articles
                    ]
                    minority = [
                        prepare_article(article, "house", name, "minority")
                        for article in min_articles
                    ]
                    committees[name] = {
                        "majority": majority,
                        "minority": minority,
                    }
                    cached_items.extend(majority)
                    cached_items.extend(minority)

                except Exception as e:
                    print(f"Error loading {name}: {e}")

            store_manual_pull("house", committees, cached_items, input_date, use_openai)

    return render_template("house.html", committees=committees, error=error, input_date=input_date, use_openai=use_openai)
