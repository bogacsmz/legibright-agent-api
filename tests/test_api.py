from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_root_is_self_documenting():
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert "description" in body and "example_curl" in body
    assert len(body["checks"]) == 5


def test_audit_minimal_metrics():
    r = client.post("/audit", json={"metrics": {"in_sample": 0.99, "holdout": 0.74}})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "NOT_TRUSTWORTHY"
    assert len(body["checks"]) == 5


def test_audit_empty_body_inconclusive():
    r = client.post("/audit", json={})
    assert r.status_code == 200
    assert r.json()["verdict"] == "INCONCLUSIVE"


def test_broken_block_is_helpful_400():
    r = client.post("/audit", json={"predictions": {"predicted": [0.1, 0.2], "outcomes": [1]}})
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "invalid_input"
    assert body["field"] == "predictions.outcomes"
    assert "equal length" in body["message"]


def test_wrong_type_remapped_to_400():
    r = client.post("/audit", json={"metrics": {"in_sample": "not-a-number"}})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_input"


def test_unknown_field_is_400():
    r = client.post("/audit", json={"bogus": 1})
    assert r.status_code == 400
