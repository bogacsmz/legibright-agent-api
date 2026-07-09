"""Adversarial regression suite — every case a pre-deploy red-team audit found.
Robustness (never crash/never green on garbage) + the honesty invariant
(no thin/degenerate input may be TRUSTWORTHY or score in the green band >=71)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _post(body):
    return client.post("/audit", json=body)


def _raw(text):
    return client.post("/audit", content=text, headers={"content-type": "application/json"})


def _status(body_or_resp, check):
    return {c["check"]: c for c in body_or_resp["checks"]}[check]["status"]


# ---- robustness: non-finite / out-of-range / oversized -> helpful 400, never a green ----

def test_infinity_in_metrics_is_400():
    r = _raw('{"metrics":{"in_sample":Infinity}}')
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_input"


def test_nan_in_predicted_is_400():
    r = _raw('{"predictions":{"predicted":[NaN,0.2],"outcomes":[0,1]}}')
    assert r.status_code == 400


def test_negative_infinity_in_holdout_is_400():
    r = _raw('{"metrics":{"in_sample":0.9,"holdout":-Infinity}}')
    assert r.status_code == 400


def test_predicted_out_of_range_is_400():
    r = _post({"predictions": {"predicted": [2.0, -1.0], "outcomes": [1, 0]}})
    assert r.status_code == 400
    assert r.json()["field"] == "predictions.predicted"


def test_outcomes_non_binary_is_400():
    r = _post({"predictions": {"predicted": [0.5, 0.5], "outcomes": [5, 7]}})
    assert r.status_code == 400
    assert r.json()["field"] == "predictions.outcomes"


def test_bool_in_sample_is_400():
    r = _post({"metrics": {"in_sample": True}})
    assert r.status_code == 400


def test_oversized_array_is_400():
    r = _post({"predictions": {"predicted": [0.5] * 100001, "outcomes": [0] * 100001}})
    assert r.status_code == 400
    assert r.json()["field"] == "predictions.predicted"


def test_too_many_columns_is_400():
    r = _post({"features": {"cols": {f"f{i}": [0.0, 1.0] for i in range(1001)}, "outcomes": [0, 1]}})
    assert r.status_code == 400
    assert r.json()["field"] == "features.cols"


# ---- honesty invariant: degenerate/thin input is NEVER green ----

def test_in_sample_only_is_inconclusive():
    b = _post({"metrics": {"in_sample": 0.99}}).json()
    assert b["verdict"] == "INCONCLUSIVE"
    assert b["trust_score"] <= 50
    assert _status(b, "overfit_flags") == "SKIPPED"


def test_perfect_on_both_single_check_is_inconclusive():
    b = _post({"metrics": {"in_sample": 1.0, "holdout": 1.0}}).json()
    assert b["verdict"] == "INCONCLUSIVE"


def test_toy_temporal_single_check_is_inconclusive():
    b = _post({"split": {"train_ts": [1, 2, 3], "test_ts": [4, 5, 6]}}).json()
    assert b["verdict"] == "INCONCLUSIVE"


def test_single_class_predictions_skipped():
    b = _post({"predictions": {"predicted": [0.9] * 60, "outcomes": [1] * 60}}).json()
    assert _status(b, "calibration_bias") == "SKIPPED"
    assert b["verdict"] == "INCONCLUSIVE"


def test_empty_predictions_skipped_not_scored_60():
    b = _post({"predictions": {"predicted": [], "outcomes": []}}).json()
    assert _status(b, "calibration_bias") == "SKIPPED"
    assert b["verdict"] == "INCONCLUSIVE"
    assert b["trust_score"] == 50


def test_material_ece_underpowered_is_not_well_calibrated():
    # ECE ~0.20 at n=50 with underpowered HL must NOT be certified "well calibrated"
    b = _post({"predictions": {"predicted": [0.3] * 50, "outcomes": [i % 2 for i in range(50)]}}).json()
    cal = {c["check"]: c for c in b["checks"]}["calibration_bias"]
    assert cal["status"] == "WARN"
    assert "well calibrated" not in (cal["headline"] or "")
    assert b["verdict"] == "INCONCLUSIVE"


def test_degenerate_battery_never_green():
    battery = [
        {"metrics": {"in_sample": 0.99}},
        {"metrics": {"in_sample": 1.0}},
        {"metrics": {"in_sample": 1.0, "holdout": 1.0}},
        {"metrics": {"in_sample": 0.8, "holdout": 0.75}},
        {"split": {"train_ts": [1, 2, 3], "test_ts": [4, 5, 6]}},
        {"split": {"train_groups": ["a", "b"], "test_groups": ["c", "d"]}},
        {"predictions": {"predicted": [0.5] * 60, "outcomes": [i % 2 for i in range(60)]}},
        {"predictions": {"predicted": [0.9] * 60, "outcomes": [1] * 60}},
        {"predictions": {"predicted": [0.3] * 50, "outcomes": [i % 2 for i in range(50)]}},
        {},
    ]
    for body in battery:
        b = _post(body).json()
        assert b["verdict"] != "TRUSTWORTHY", (body, b["verdict"])
        assert b["trust_score"] <= 70, (body, b["trust_score"])


def test_determinism_same_input_same_result():
    body = {"split": {"train_ts": [1, 2, 3], "test_ts": [4, 5, 6]},
            "features": {"cols": {"a": [float(i) for i in range(60)],
                                   "b": [float(i % 3) for i in range(60)]},
                          "outcomes": [i % 2 for i in range(60)]}}
    seen = {(_post(body).json()["verdict"], _post(body).json()["trust_score"]) for _ in range(5)}
    assert len(seen) == 1
