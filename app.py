from flask import Flask, render_template

from config import Config
from routes.gmail import gmail
from routes.news import news
from routes.senate import senate
from routes.house import house
from routes.saved_articles import saved_articles
from routes.add_event import add_event
from routes.add_event_pull import add_event_pull

from production.routes import production

from features.pretty_date import pretty_date
from session_backend import configure_session

app = Flask(__name__)
app.config.from_object(Config)
configure_session(app)


@app.context_processor
def asset_helpers():
    def asset_url(filename: str) -> str:
        if app.config.get("USE_PUBLIC_ASSETS", False):
            return f"/assets/{filename}"
        return f"/static/{filename}"

    return {"asset_url": asset_url}

app.register_blueprint(gmail)
app.register_blueprint(news)
app.register_blueprint(house)
app.register_blueprint(senate)
app.register_blueprint(saved_articles)
app.register_blueprint(add_event)
app.register_blueprint(add_event_pull)

app.register_blueprint(production, url_prefix="/production")

app.jinja_env.filters["pretty_date"] = pretty_date

@app.route("/")
def home():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)
