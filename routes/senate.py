from flask import Blueprint, render_template, request
from datetime import datetime, timedelta

from features.classify import classify
from sources.catalog import SENATE_SOURCES

senate = Blueprint("senate", __name__)

@senate.route("/senate", methods=["GET", "POST"])
def senate_view():
    input_date = (datetime.today() - timedelta(days=3)).strftime("%Y-%m-%d")
    start_date = None
    error = None
    committees = {}
    use_openai = False 

    if request.method == "POST":
        input_date = request.form.get("start_date", "").strip()
        use_openai = "use_openai" in request.form

        if input_date:
            try:
                start_date = datetime.strptime(input_date, "%Y-%m-%d").date()
            except ValueError:
                error = "Invalid date."

        if not error and start_date:
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
                            print("classifying")
                            article["suggestion"] = classify(article["title"])
                        tag = article.get("tag", "")
                        if tag in grouped:
                            grouped[tag].append(article)

                    committees[name] = grouped
                except Exception as e:
                    print(f"Error loading {name}: {e}")

    return render_template("senate.html", committees=committees, error=error, input_date=input_date, use_openai=use_openai)
