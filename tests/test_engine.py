import pytest
from app.schemas import AuditRequest
from app.audit import run_audit
from app.errors import InvalidInput

CHECK_ORDER = ["temporal_leakage", "group_leakage", "target_leakage",
               "calibration_bias", "overfit_flags"]


def _by_check(resp):
    return {c.check: c for c in resp.checks}


def test_empty_body_all_skipped_inconclusive():
    r = run_audit(AuditRequest())
    assert [c.check for c in r.checks] == CHECK_ORDER
    assert all(c.status == "SKIPPED" for c in r.checks)
    assert r.verdict == "INCONCLUSIVE"
    assert r.trust_score == 50
    assert r.counts["skipped"] == 5


def test_minimal_metrics_overfit_fail():
    r = run_audit(AuditRequest(**{"metrics": {"in_sample": 0.99, "holdout": 0.74}}))
    by = _by_check(r)
    assert by["overfit_flags"].status == "FAIL"
    assert by["temporal_leakage"].status == "SKIPPED"
    assert r.verdict == "NOT_TRUSTWORTHY"
    assert 0 <= r.trust_score <= 40


def test_honest_overfit_pass_trustworthy():
    r = run_audit(AuditRequest(**{"metrics": {"in_sample": 0.79, "holdout": 0.57}}))
    by = _by_check(r)
    assert by["overfit_flags"].status == "PASS"
    assert r.verdict == "TRUSTWORTHY"
    assert r.trust_score == 100


def test_temporal_leakage_fail():
    r = run_audit(AuditRequest(**{"split": {"train_ts": [1, 2, 3], "test_ts": [2, 3, 4]}}))
    by = _by_check(r)
    assert by["temporal_leakage"].status == "FAIL"
    assert by["group_leakage"].status == "SKIPPED"
    assert r.verdict == "NOT_TRUSTWORTHY"


def test_predictions_length_mismatch_raises():
    with pytest.raises(InvalidInput) as ei:
        run_audit(AuditRequest(**{"predictions": {"predicted": [0.1, 0.2], "outcomes": [1]}}))
    assert ei.value.field == "predictions.outcomes"


def test_lone_train_ts_raises():
    with pytest.raises(InvalidInput) as ei:
        run_audit(AuditRequest(**{"split": {"train_ts": [1, 2, 3]}}))
    assert "test_ts" in ei.value.message


def test_feature_column_length_mismatch_raises():
    with pytest.raises(InvalidInput) as ei:
        run_audit(AuditRequest(**{"features": {"cols": {"f1": [1, 2, 3]}, "outcomes": [1, 0]}}))
    assert ei.value.field.startswith("features")


def test_single_warn_is_inconclusive_score_60():
    # 10 rows (<50) -> calibration_bias WARN (not certified); it's the only check that runs
    r = run_audit(AuditRequest(**{"predictions": {"predicted": [0.1] * 10, "outcomes": [0, 1] * 5}}))
    by = _by_check(r)
    assert by["calibration_bias"].status == "WARN"
    assert [c.status for c in r.checks if c.check != "calibration_bias"] == ["SKIPPED"] * 4
    assert r.verdict == "INCONCLUSIVE"
    assert r.trust_score == 60
    assert r.counts["warn"] == 1
