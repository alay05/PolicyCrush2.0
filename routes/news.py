from flask import Blueprint, render_template, request
from datetime import datetime, timedelta

from features.classify import classify
from sources.catalog import NEWS_SOURCES

news = Blueprint("news", __name__)

@news.route("/news", methods=["GET", "POST"])
def news_view():
    input_date = (datetime.today() - timedelta(days=3)).strftime("%Y-%m-%d")
    start_date = None
    error = None
    articles = {}
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
            for name, fetch in NEWS_SOURCES.items():
                try:
                    payload = fetch(start_date) 

                    if use_openai:
                      print("yes")
                      for article in payload["articles"]:
                          print("classifying")
                          article["suggestion"] = classify(article["title"])
                    
                    articles[name] = {
                        "url": payload["url"],
                        "items": payload["articles"]
                    }
                    

                except Exception as e:
                    print(f"Error fetching {name}: {e}")

    return render_template("news.html", articles=articles, error=error, input_date=input_date, use_openai=use_openai)
