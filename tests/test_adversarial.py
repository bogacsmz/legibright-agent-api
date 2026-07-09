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
        {"split": {"train_ts": [1], "test_ts": [2], "train_groups": ["a"], "test_groups": ["b"]}},
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


def test_split_block_cannot_self_certify():
    # temporal + group both come from the ONE split block; two OKs from one input is NOT coverage
    for split in (
        {"train_ts": [1], "test_ts": [2], "train_groups": ["a"], "test_groups": ["b"]},        # reviewer repro
        {"train_ts": [1, 2, 3], "test_ts": [4, 5, 6],
         "train_groups": ["a", "b", "c"], "test_groups": ["d", "e", "f"]},                       # both PASS
    ):
        b = _post({"split": split}).json()
        assert b["verdict"] != "TRUSTWORTHY", (split, b["verdict"])
        assert b["trust_score"] <= 70, (split, b["trust_score"])


def test_two_distinct_blocks_still_reach_trustworthy():
    # green must remain reachable when evidence comes from >=2 DIFFERENT input blocks on real data
    b = _post({"split": {"train_ts": [float(i) for i in range(25)],
                          "test_ts": [float(i) for i in range(100, 125)]},
               "metrics": {"in_sample": 0.79, "holdout": 0.57}}).json()
    assert b["verdict"] == "TRUSTWORTHY"
    assert b["trust_score"] == 100


def test_calibration_never_passes_above_material_ece():
    # invariant: an OK/PASS calibration is never certified when ECE >= 0.03 (material floor)
    for pred in (0.30, 0.35, 0.40, 0.45):
        b = _post({"predictions": {"predicted": [pred] * 80,
                                    "outcomes": [i % 2 for i in range(80)]}}).json()
        cal = {c["check"]: c for c in b["checks"]}["calibration_bias"]
        ece = (cal.get("metrics") or {}).get("ece", 0.0)
        if ece >= 0.03:
            assert cal["status"] in ("WARN", "FAIL"), (pred, ece, cal["status"])
            assert "well calibrated" not in (cal["headline"] or ""), (pred, cal["headline"])


def test_no_holdout_overfit_never_certifies():
    # overfit OK without a holdout must NOT count as evidence — no param trick may reach green
    for m in (
        {"in_sample": 1.0, "n_cells_scanned": 2},       # n_cells below the ~44 flag threshold
        {"in_sample": 0.99, "abs_alarm": 2.0},           # abs_alarm set but not tripped
        {"in_sample": 1.0},                               # bare
        {"in_sample": -5.0, "n_cells_scanned": 10},
    ):
        b = _post({"metrics": m}).json()
        of = {c["check"]: c for c in b["checks"]}["overfit_flags"]
        assert of["status"] == "SKIPPED", (m, of)
        assert b["verdict"] == "INCONCLUSIVE", (m, b["verdict"])
    # and it can't be laundered into green by pairing with a clean split block
    for m in ({"in_sample": 1.0, "n_cells_scanned": 2}, {"in_sample": 0.99, "abs_alarm": 2.0}):
        b = _post({"split": {"train_ts": [1, 2, 3], "test_ts": [4, 5, 6]}, "metrics": m}).json()
        assert b["verdict"] != "TRUSTWORTHY", (m, b["verdict"])
        assert b["trust_score"] <= 70, (m, b["trust_score"])


def test_no_holdout_real_redflag_still_fires():
    # a genuine no-holdout red flag (many cells scanned) must still be reported, not skipped
    b = _post({"metrics": {"in_sample": 0.9, "n_cells_scanned": 100}}).json()
    of = {c["check"]: c for c in b["checks"]}["overfit_flags"]
    assert of["status"] in ("WARN", "FAIL"), of
    assert b["verdict"] != "TRUSTWORTHY"


def test_tiny_clean_split_does_not_count_as_evidence():
    # a clean cut on 3 timestamps + a real overfit pass must NOT reach green (split is below floor)
    b = _post({"split": {"train_ts": [1, 2, 3], "test_ts": [4, 5, 6]},
               "metrics": {"in_sample": 0.79, "holdout": 0.57}}).json()
    by = {c["check"]: c for c in b["checks"]}
    assert by["temporal_leakage"]["status"] == "SKIPPED"
    assert b["verdict"] == "INCONCLUSIVE"
    assert b["trust_score"] <= 70


def test_perfect_on_both_is_flagged_not_certified():
    # near-perfect on BOTH train and holdout = leakage signature -> WARN, never green
    for m in ({"in_sample": 1.0, "holdout": 1.0}, {"in_sample": 0.99, "holdout": 0.995}):
        b = _post({"metrics": m}).json()
        of = {c["check"]: c for c in b["checks"]}["overfit_flags"]
        assert of["status"] == "WARN", (m, of)
        assert b["verdict"] == "INCONCLUSIVE"
    # and it cannot be laundered into green by adding a real clean split
    b = _post({"split": {"train_ts": [float(i) for i in range(25)],
                          "test_ts": [float(i) for i in range(100, 125)]},
               "metrics": {"in_sample": 1.0, "holdout": 1.0}}).json()
    assert b["verdict"] != "TRUSTWORTHY"  # overfit WARN -> INCONCLUSIVE


def test_padded_duplicate_timestamps_do_not_count_as_evidence():
    # 20 IDENTICAL timestamps/side carry no more temporal evidence than 3 points -> must not count
    b = _post({"split": {"train_ts": [1.0] * 20, "test_ts": [2.0] * 20},
               "metrics": {"in_sample": 0.8, "holdout": 0.79}}).json()
    by = {c["check"]: c for c in b["checks"]}
    assert by["temporal_leakage"]["status"] == "SKIPPED"
    assert b["verdict"] != "TRUSTWORTHY"
    assert b["trust_score"] <= 70
