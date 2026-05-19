from flask import Blueprint, jsonify, request, abort
from .db import db
from .models import Item

bp = Blueprint("items", __name__, url_prefix="/api")

@bp.get("/health")
def health():
    return {"status": "ok", "service": "${{ values.name }}"}

@bp.get("/items")
def list_items():
    return jsonify([i.to_dict() for i in Item.query.all()])

@bp.post("/items")
def create_item():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        abort(400, "name required")
    item = Item(name=data["name"])
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict()), 201