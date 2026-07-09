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


def test_internal_error_is_clean_500(monkeypatch):
    from app import main
    def boom(req):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(main, "run_audit", boom)
    local = TestClient(app, raise_server_exceptions=False)
    r = local.post("/audit", json={"metrics": {"in_sample": 0.9}})
    assert r.status_code == 500
    body = r.json()
    assert body["error"] == "internal_error"
    assert "field" in body               # envelope contract holds on the 500 path too
    assert "secret internal detail" not in r.text   # no internal detail leaks


def test_group_leakage_fail():
    r = client.post("/audit", json={"split": {
        "train_groups": ["a", "b", "c"], "test_groups": ["a", "b", "d"], "entity": "team"}})
    by = {c["check"]: c for c in r.json()["checks"]}
    assert by["group_leakage"]["status"] == "FAIL"


def test_target_leakage_fail():
    n = 60
    labels = [i % 2 for i in range(n)]
    leaky = [float(y) for y in labels]          # feature == label
    r = client.post("/audit", json={"features": {"cols": {"leak": leaky}, "outcomes": labels}})
    by = {c["check"]: c for c in r.json()["checks"]}
    assert by["target_leakage"]["status"] == "FAIL"


def test_calibration_runs_on_enough_rows():
    # 100 well-separated, well-calibrated points -> calibration runs (PASS or WARN, not SKIPPED)
    preds = [0.05] * 50 + [0.95] * 50
    outs = [0] * 50 + [1] * 50
    r = client.post("/audit", json={"predictions": {"predicted": preds, "outcomes": outs}})
    by = {c["check"]: c for c in r.json()["checks"]}
    assert by["calibration_bias"]["status"] in {"PASS", "WARN"}


def test_full_multi_block_request():
    r = client.post("/audit", json={
        "target": "model_x",
        "split": {"train_ts": [float(i) for i in range(25)],
                   "test_ts": [float(i) for i in range(100, 125)]},
        "metrics": {"in_sample": 0.99, "holdout": 0.74},
    })
    body = r.json()
    assert body["target"] == "model_x"
    assert body["verdict"] == "NOT_TRUSTWORTHY"  # overfit FAIL dominates
    by = {c["check"]: c for c in body["checks"]}
    assert by["temporal_leakage"]["status"] == "PASS"
    assert by["overfit_flags"]["status"] == "FAIL"
