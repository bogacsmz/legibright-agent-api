"""Trust Audit API — stateless, agent-callable statistical-honesty auditor."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .audit import run_audit
from .errors import InvalidInput
from .schemas import AuditRequest, AuditResponse

app = FastAPI(
    title="Trust Audit API",
    description="Stateless statistical-honesty auditor: leakage, overfit, calibration.",
    version="1.0.0",
)

_CHECKS = [
    {"check": "temporal_leakage",
     "catches": "training data dated after the test cutoff — future leaks into the model",
     "input": "split.train_ts + split.test_ts"},
    {"check": "group_leakage",
     "catches": "the same entity in train and test — the model memorizes it, not the pattern",
     "input": "split.train_groups + split.test_groups"},
    {"check": "target_leakage",
     "catches": "a feature that almost perfectly predicts the label (encodes the outcome)",
     "input": "features.cols + features.outcomes"},
    {"check": "calibration_bias",
     "catches": "statistically-significant probability miscalibration a single score hides",
     "input": "predictions.predicted + predictions.outcomes"},
    {"check": "overfit_flags",
     "catches": "too-good in-sample, near-perfect memorization, holdout collapse, multiple-testing luck",
     "input": "metrics.in_sample (+holdout, n_cells_scanned)"},
]

_EXAMPLE_BODY = {"metrics": {"in_sample": 0.99, "holdout": 0.74}}
_EXAMPLE_CURL = (
    "curl -sX POST http://localhost:8000/audit -H 'content-type: application/json' "
    "-d '{\"metrics\":{\"in_sample\":0.99,\"holdout\":0.74}}'"
)


@app.exception_handler(InvalidInput)
async def _invalid_input_handler(_: Request, exc: InvalidInput) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": "invalid_input", "message": exc.message, "field": exc.field},
    )


@app.exception_handler(RequestValidationError)
async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    err = exc.errors()[0]
    loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
    msg = err.get("msg", "invalid request")
    return JSONResponse(
        status_code=400,
        content={
            "error": "invalid_input",
            "message": f"{loc}: {msg}" if loc else msg,
            "field": loc or None,
        },
    )


@app.exception_handler(Exception)
async def _unexpected_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error",
                 "message": "an internal error occurred while auditing",
                 "field": None},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def root() -> dict:
    return {
        "service": "Trust Audit API",
        "description": "POST /audit with any subset of {split, predictions, features, metrics}; "
                       "each present block runs its check, absent blocks are skipped. Returns a "
                       "trust_score (0-100) + verdict (TRUSTWORTHY/INCONCLUSIVE/NOT_TRUSTWORTHY).",
        "checks": _CHECKS,
        "example_request": _EXAMPLE_BODY,
        "example_curl": _EXAMPLE_CURL,
    }


@app.post("/audit", response_model=AuditResponse)
def audit(req: AuditRequest) -> AuditResponse:
    return run_audit(req)
