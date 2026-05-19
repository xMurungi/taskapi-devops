from flask import Flask
from .db import db
from prometheus_flask_exporter import PrometheusMetrics

def create_app(config=None):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///data/${{ values.name }}.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    if config:
        app.config.update(config)
    db.init_app(app)
    PrometheusMetrics(app)
    from .routes import bp
    app.register_blueprint(bp)
    with app.app_context():
        db.create_all()
    return app
