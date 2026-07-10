"""Pydantic request/response models for the Trust Audit API.

Types only. Cross-field/semantic validation (pairing, equal-length) lives in
app/audit.py so it can raise InvalidInput with precise messages.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class SplitBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    train_ts: list[float] | None = None
    test_ts: list[float] | None = None
    train_groups: list[Any] | None = None
    test_groups: list[Any] | None = None
    entity: str = "entity"


class PredictionsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predicted: list[float]
    outcomes: list[int]


class FeaturesBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cols: dict[str, list[float]]
    outcomes: list[int]


class MetricsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    in_sample: float
    holdout: float | None = None
    n_cells_scanned: int = 1
    bounded: bool = True
    abs_alarm: float | None = None
    metric: str = "score"

    @field_validator("in_sample", "holdout", "abs_alarm", "n_cells_scanned", mode="before")
    @classmethod
    def _reject_bool(cls, v):
        if isinstance(v, bool):
            raise ValueError("must be a number, not a boolean")
        return v


class AuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = "unnamed"
    split: SplitBlock | None = None
    predictions: PredictionsBlock | None = None
    features: FeaturesBlock | None = None
    metrics: MetricsBlock | None = None


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: str
    status: str  # PASS | WARN | FAIL | SKIPPED
    headline: str | None = None
    detail: str | None = None
    metrics: dict[str, Any] | None = None
    reason: str | None = None


class AuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str
    trust_score: int
    verdict: str
    summary: str
    counts: dict[str, int]
    checks: list[CheckResult]
    certificate: dict[str, Any] | None = None


class VerifyRequest(BaseModel):
    """Request body for POST /verify: POST the certificate object exactly as
    it appeared in an /audit response's `certificate` field, e.g.
    {"claim": {...}, "content_id": "...", "signature": "...",
     "algorithm": "Ed25519", "public_key": "...", "key_id": "..."}.

    Every field is optional here on purpose: a malformed/forged/incomplete
    certificate is a normal *answer* (valid: false), not a request error, so
    we don't let pydantic 400 on a missing/odd field — verify_certificate()
    does its own defensive validation and always returns a verdict. Extra
    fields are allowed so a caller can pass a certificate through unmodified
    even if it carries additional metadata."""
    model_config = ConfigDict(extra="allow")
    claim: Any = None
    content_id: str | None = None
    signature: str | None = None
    algorithm: str | None = None
    public_key: str | None = None
    key_id: str | None = None


class VerifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid: bool
    reason: str
    claim: dict[str, Any] | None = None
