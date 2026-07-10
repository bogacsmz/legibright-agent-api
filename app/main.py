"""Trust Audit API — stateless, agent-callable statistical-honesty auditor."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from .audit import run_audit
from .certificate import KEY_ID, PUBLIC_KEY_HEX, issue_certificate, verify_certificate
from .errors import InvalidInput
from .schemas import AuditRequest, AuditResponse, VerifyRequest, VerifyResponse

_SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"

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
        "tagline": "the honesty gate for agent-to-agent claims — verify a peer's number "
                   "(accuracy, backtest ROI, win-rate, confidence) before you trust or act on it",
        "description": "POST /audit with any subset of {split, predictions, features, metrics}; "
                       "each present block runs its check, absent blocks are skipped. Returns a "
                       "trust_score (0-100) + verdict (TRUSTWORTHY/INCONCLUSIVE/NOT_TRUSTWORTHY).",
        "checks": _CHECKS,
        "example_request": _EXAMPLE_BODY,
        "example_curl": _EXAMPLE_CURL,
        "trust_note": "verdict requires no probed failure across ≥2 independent input blocks "
                      "(split/predictions/features/metrics); TRUSTWORTHY means no leakage/overfit/"
                      "calibration failure was found, not that a model is useful. See docs/VERIFICATION.md.",
        "public_key": PUBLIC_KEY_HEX,
        "key_id": KEY_ID,
        "signature_algorithm": "Ed25519",
        "certificate_note": "every /audit response carries an Ed25519-signed, portable trust "
                            "certificate (field `certificate`) that any agent can carry and verify "
                            "offline — without re-running the audit — via POST /verify. A "
                            "TRUSTWORTHY certificate attests that no failure was found across ≥2 "
                            "independent evidence blocks; it is not a claim that the underlying "
                            "model is good.",
    }


@app.get("/skill.md")
def skill_md() -> PlainTextResponse:
    try:
        return PlainTextResponse(
            _SKILL_MD.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")
    except OSError:
        return PlainTextResponse("SKILL.md not found", status_code=404)


@app.post("/audit", response_model=AuditResponse)
def audit(req: AuditRequest) -> AuditResponse:
    resp = run_audit(req)
    resp.certificate = issue_certificate(req, resp)
    return resp


@app.post("/verify", response_model=VerifyResponse)
def verify(req: VerifyRequest) -> VerifyResponse:
    """Verify a portable trust certificate offline (no re-audit). A bad,
    forged, or tampered certificate is a normal answer — HTTP 200 with
    valid: false — not a 400/500."""
    result = verify_certificate(req.model_dump())
    return VerifyResponse(**result)


def main() -> None:
    """Entrypoint that reads $PORT from the environment itself, so the start command
    carries no shell-expanded `$PORT` (works identically under Docker, a Procfile, or
    a bare `python -m app.main`)."""
    import os

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
