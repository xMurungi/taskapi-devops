import pytest
from app import createApp

@pytest.fixture
def client():
    app = createApp(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"
        }
    )
    with app.test_client() as c:
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

