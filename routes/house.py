from flask import Blueprint, render_template, request
from datetime import datetime, timedelta

from features.classify import classify
from sources.catalog import HOUSE_SOURCES

house = Blueprint("house", __name__)

@house.route("/house", methods=["GET", "POST"])
def house_view():
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
            for name, fetch in HOUSE_SOURCES.items():
                try:
                    maj_articles = fetch["majority"](start_date)
                    min_articles = fetch["minority"](start_date)

                    committees[name] = {
                        "majority": maj_articles,
                        "minority": min_articles,
                    }

                    if use_openai:
                      for article in maj_articles:
                          print("classifying")
                          article["suggestion"] = classify(article["title"])
                      for article in min_articles:
                          print("classifying")
                          article["suggestion"] = classify(article["title"])
                        
                except Exception as e:
                    print(f"Error loading {name}: {e}")

    return render_template("house.html", committees=committees, error=error, input_date=input_date, use_openai=use_openai)
