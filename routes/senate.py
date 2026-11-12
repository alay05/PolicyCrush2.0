from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request

from features.classify import classify
from routes.saved_articles import get_manual_pull, prepare_article, store_manual_pull
from sources.catalog import SENATE_SOURCES
from sources.senate.hearings import fetch_senate_hearings

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
            with ThreadPoolExecutor(max_workers=8) as executor:
                hearing_future = executor.submit(fetch_senate_hearings, start_date)
                source_futures = {
                    name: executor.submit(fetch, start_date)
                    for name, fetch in SENATE_SOURCES.items()
                }

                try:
                    hearing_results = hearing_future.result()
                except Exception as e:
                    print(f"Error loading Senate hearings from Congress.gov: {e}")
                    hearing_results = {}

                source_payloads = {}
                for name, future in source_futures.items():
                    try:
                        source_payloads[name] = future.result()
                    except Exception as e:
                        print(f"Error loading {name}: {e}")

            for name in SENATE_SOURCES:
                try:
                    payload = source_payloads.get(name)
                    if not payload:
                        continue
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

                    for article in hearing_results.get(name, []):
                        if use_openai:
                            article["suggestion"] = classify(article["title"])
                        prepared = prepare_article(article, "senate", name, "hearing")
                        grouped["hearing"].append(prepared)
                        cached_items.append(prepared)

                    committees[name] = grouped
                except Exception as e:
                    print(f"Error loading {name}: {e}")

            store_manual_pull("senate", committees, cached_items, input_date, use_openai)

    return render_template("senate.html", committees=committees, error=error, input_date=input_date, use_openai=use_openai)
