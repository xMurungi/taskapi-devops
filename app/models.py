from .db import db
from datetime import datetime, timezone

class Task(db.Model):
    id      = db.Column(db.Integer, primary_key = True)
    title   = db.Column(db.String(200), nullable = False)
    done    = db.Column(db.Boolean, default = False)
    created = db.Column(db.DateTime, default = lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id":self.id,
            "title":self.title,
            "done":self.done,
            "created":str(self.created)
        }
    