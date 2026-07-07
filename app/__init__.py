import os
from flask import Flask
from .db import db
from prometheus_flask_exporter import PrometheusMetrics

def createApp(config = None):
    app = Flask(__name__)

    # 1. Look for DATABASE_URL from K8s Secret, fallback to local sqlite
    default_db = "sqlite:///tasks.db"

    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", default_db)
    app.config["SQLALCHEMY_TRACK_MODIFICATION"] = False

    if config:
        app.config.update(config)

    db.init_app(app)

    # initialise metrics — this adds /metrics endpoint automatically
    metrics = PrometheusMetrics(app)

    # static info metric — appears as a label on all metrics
    metrics.info("app_info", "Task API info", version="1.0")

    from .routes import bp
    app.register_blueprint(bp)

    with app.app_context():
        db.create_all()

    return app    
