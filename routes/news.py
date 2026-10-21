from flask import Blueprint, render_template, request
from datetime import datetime, timedelta

from features.classify import classify
from routes.saved_articles import get_manual_pull, prepare_article, store_manual_pull
from sources.catalog import NEWS_SOURCES

news = Blueprint("news", __name__)

@news.route("/news", methods=["GET", "POST"])
def news_view():
    input_date = (datetime.today() - timedelta(days=3)).strftime("%Y-%m-%d")
    start_date = None
    error = None
    articles = {}
    use_openai = False

    if request.method == "GET":
        cached = get_manual_pull("news")
        if cached:
            input_date = cached.get("input_date", input_date)
            use_openai = bool(cached.get("use_openai", False))
            articles = cached.get("results") or {}

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
            for name, fetch in NEWS_SOURCES.items():
                try:
                    payload = fetch(start_date)

                    if use_openai:
                        for article in payload["articles"]:
                            article["suggestion"] = classify(article["title"])

                    prepared = [
                        prepare_article(article, "news", name)
                        for article in payload["articles"]
                    ]
                    articles[name] = {
                        "url": payload["url"],
                        "items": prepared,
                    }
                    cached_items.extend(prepared)

                except Exception as e:
                    print(f"Error fetching {name}: {e}")

            store_manual_pull("news", articles, cached_items, input_date, use_openai)

    return render_template("news.html", articles=articles, error=error, input_date=input_date, use_openai=use_openai)
