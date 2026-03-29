from flask import Blueprint, jsonify, request, abort
from .db import db
from .models import Task

bp = Blueprint("tasks", __name__, url_prefix="/api")

@bp.get("/health")
def health():
    return {"status":"ok"}

@bp.get("/tasks")
def get_tasks():
    tasks = Task.query.all()
    return jsonify([t.to_dict() for t in tasks])

@bp.post("/tasks")
def post_task():
    data = request.get_json(silent=True) or {}
    if not data.get("title"):
        abort(400, "Title required")
    
    t = Task(title=data["title"])
    db.session.add(t)
    db.session.commit()
    return jsonify(t.to_dict()), 201

@bp.patch("/tasks/<int:task_id>")
def update_task(task_id):
    t = Task.query.get_or_404(task_id)
    data = request.get_json(silent=True) or {}

    if "done" in data:
        t.done = data["done"]
    if "title" in data:
        t.title = data["title"]
    
    db.session.commit()
    return jsonify(t.to_dict())

@bp.delete("/tasks/<int:task_id>")
def delete_task(task_id):
    t = Task.query.get_or_404(task_id)
    db.session.delete(t)
    db.session.commit()
    return "", 204
