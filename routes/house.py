from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request

from features.classify import classify
from routes.saved_articles import get_manual_pull, prepare_article, store_manual_pull
from sources.catalog import HOUSE_COMMITTEE_URLS, HOUSE_SOURCES
from sources.house.hearings import fetch_house_hearings

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
            for name, data in committees.items():
                data.setdefault("url", HOUSE_COMMITTEE_URLS.get(name, ""))

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
            with ThreadPoolExecutor(max_workers=10) as executor:
                hearing_future = executor.submit(fetch_house_hearings, start_date)
                source_futures = {
                    name: (
                        executor.submit(fetch["majority"], start_date),
                        executor.submit(fetch["minority"], start_date),
                    )
                    for name, fetch in HOUSE_SOURCES.items()
                }

                try:
                    hearing_results = hearing_future.result()
                except Exception as e:
                    print(f"Error loading House hearings: {e}")
                    hearing_results = {}

                fetched_sources = {}
                for name, (majority_future, minority_future) in source_futures.items():
                    try:
                        fetched_sources[name] = (
                            majority_future.result(),
                            minority_future.result(),
                        )
                    except Exception as e:
                        print(f"Error loading {name}: {e}")
                        fetched_sources[name] = ([], [])

            for name in HOUSE_SOURCES:
                maj_articles, min_articles = fetched_sources[name]
                hearing_articles = hearing_results.get(name, [])

                if use_openai:
                    for article in maj_articles:
                        article["suggestion"] = classify(article["title"])
                    for article in min_articles:
                        article["suggestion"] = classify(article["title"])
                    for article in hearing_articles:
                        article["suggestion"] = classify(article["title"])

                majority = [
                    prepare_article(article, "house", name, "majority")
                    for article in maj_articles
                ]
                minority = [
                    prepare_article(article, "house", name, "minority")
                    for article in min_articles
                ]
                hearings = [
                    prepare_article(article, "house", name, "hearing")
                    for article in hearing_articles
                ]
                committees[name] = {
                    "url": HOUSE_COMMITTEE_URLS.get(name, ""),
                    "majority": majority,
                    "minority": minority,
                    "hearing": hearings,
                }
                cached_items.extend(majority)
                cached_items.extend(minority)
                cached_items.extend(hearings)

            store_manual_pull("house", committees, cached_items, input_date, use_openai)

    return render_template("house.html", committees=committees, error=error, input_date=input_date, use_openai=use_openai)
