import pytest
from app import createApp
from app.db import db  # Import your db instance here

@pytest.fixture(scope="session")
def app():
    app = createApp(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"
        }
    )
    yield app

@pytest.fixture
def client(app):
    with app.test_client() as c:
        with app.app_context():
            # Clear the database tables before each test to keep them isolated
            db.session.remove()
            db.drop_all()
            db.create_all()
        yield c

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200

def test_create_and_get(client):
    r = client.post("/api/tasks", json={"title": "buy milk"})
    assert r.status_code == 201
    r = client.get("/api/tasks")
    assert len(r.get_json()) == 1

def test_missing_title(client):
    r = client.post("/api/tasks", json={})
    assert r.status_code == 400
    