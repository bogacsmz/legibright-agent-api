import pytest
from pydantic import ValidationError
from app.schemas import AuditRequest, MetricsBlock, AuditResponse, CheckResult
from app.errors import InvalidInput


def test_minimal_metrics_request_parses():
    req = AuditRequest(**{"metrics": {"in_sample": 0.99, "holdout": 0.74}})
    assert req.metrics.in_sample == 0.99
    assert req.metrics.n_cells_scanned == 1
    assert req.target == "unnamed"
    assert req.split is None and req.predictions is None and req.features is None


def test_empty_body_parses():
    req = AuditRequest()
    assert req.split is None and req.metrics is None


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        AuditRequest(**{"metrics": {"in_sample": 0.9, "bogus": 1}})


def test_invalid_input_carries_field():
    e = InvalidInput("lengths differ", field="predictions.outcomes")
    assert e.message == "lengths differ"
    assert e.field == "predictions.outcomes"


def test_response_model_shape():
    r = AuditResponse(
        target="t", trust_score=100, verdict="TRUSTWORTHY", summary="ok",
        counts={"pass": 1, "warn": 0, "fail": 0, "skipped": 4},
        checks=[CheckResult(check="overfit_flags", status="PASS", headline="fine")],
    )
    assert r.checks[0].status == "PASS"
