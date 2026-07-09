"""Audit engine: validate the request, run the check for each present block,
skip absent blocks, and aggregate Findings into a verdict + trust score.

Verdict/score are lifted verbatim (in behavior) from Legibright's AuditReport,
computed over the checks that RAN only. SKIPPED = the input block is absent.
"""
from __future__ import annotations

from .checks.base import Finding, Severity
from .checks.calibration_bias import CalibrationBiasCheck
from .checks.group_leakage import GroupLeakageCheck
from .checks.overfit_flags import OverfitFlagsCheck
from .checks.target_leakage import TargetLeakageCheck
from .checks.temporal_leakage import TemporalLeakageCheck
from .errors import InvalidInput
from .schemas import AuditRequest, AuditResponse, CheckResult

_STATUS = {Severity.OK: "PASS", Severity.WARN: "WARN", Severity.FAIL: "FAIL"}


def _validate(req: AuditRequest) -> None:
    """Present-but-broken blocks → InvalidInput (→ HTTP 400). Absent blocks are fine."""
    s = req.split
    if s is not None:
        if (s.train_ts is None) != (s.test_ts is None):
            missing = "test_ts" if s.train_ts is not None else "train_ts"
            raise InvalidInput(
                f"split.{missing} is required when its counterpart is provided — "
                "temporal leakage needs both train_ts and test_ts.",
                field=f"split.{missing}",
            )
        if (s.train_groups is None) != (s.test_groups is None):
            missing = "test_groups" if s.train_groups is not None else "train_groups"
            raise InvalidInput(
                f"split.{missing} is required when its counterpart is provided — "
                "group leakage needs both train_groups and test_groups.",
                field=f"split.{missing}",
            )

    p = req.predictions
    if p is not None and len(p.predicted) != len(p.outcomes):
        raise InvalidInput(
            f"predictions.predicted has {len(p.predicted)} items but predictions.outcomes "
            f"has {len(p.outcomes)} — they must be equal length.",
            field="predictions.outcomes",
        )

    f = req.features
    if f is not None:
        if not f.cols:
            raise InvalidInput(
                "features.cols must contain at least one column.", field="features.cols"
            )
        for name, vals in f.cols.items():
            if len(vals) != len(f.outcomes):
                raise InvalidInput(
                    f"features.cols['{name}'] has {len(vals)} items but features.outcomes "
                    f"has {len(f.outcomes)} — every column must match outcomes length.",
                    field=f"features.cols.{name}",
                )


def _skip(check: str, reason: str) -> tuple[CheckResult, None]:
    return CheckResult(check=check, status="SKIPPED", reason=reason), None


def _ran(finding: Finding) -> tuple[CheckResult, Finding]:
    return (
        CheckResult(
            check=finding.check,
            status=_STATUS[finding.severity],
            headline=finding.headline,
            detail=finding.detail or None,
            metrics=finding.metrics or None,
        ),
        finding,
    )


def run_audit(req: AuditRequest) -> AuditResponse:
    _validate(req)

    results: list[CheckResult] = []
    findings: list[Finding] = []

    # 1. temporal_leakage
    s = req.split
    if s is not None and s.train_ts is not None and s.test_ts is not None:
        if not s.train_ts or not s.test_ts:
            cr, fn = _skip("temporal_leakage", "temporal split arrays are empty — nothing to test")
        else:
            cr, fn = _ran(TemporalLeakageCheck().run(train_ts=s.train_ts, test_ts=s.test_ts))
    else:
        cr, fn = _skip("temporal_leakage", "no `split.train_ts`/`split.test_ts` provided")
    results.append(cr)
    if fn is not None:
        findings.append(fn)

    # 2. group_leakage
    if s is not None and s.train_groups is not None and s.test_groups is not None:
        if not s.train_groups or not s.test_groups:
            cr, fn = _skip("group_leakage", "group arrays are empty — nothing to test")
        else:
            cr, fn = _ran(GroupLeakageCheck().run(
                train_groups=s.train_groups, test_groups=s.test_groups, entity=s.entity))
    else:
        cr, fn = _skip("group_leakage", "no `split.train_groups`/`split.test_groups` provided")
    results.append(cr)
    if fn is not None:
        findings.append(fn)

    # 3. target_leakage
    f = req.features
    if f is not None:
        y = f.outcomes
        pos = sum(1 for v in y if v == 1)
        if len(y) < 30 or pos == 0 or pos == len(y):
            cr, fn = _skip("target_leakage",
                           "target leakage needs ≥30 rows with both label classes present — cannot certify")
        else:
            cr, fn = _ran(TargetLeakageCheck().run(features=f.cols, outcomes=f.outcomes))
    else:
        cr, fn = _skip("target_leakage", "no `features` block provided")
    results.append(cr)
    if fn is not None:
        findings.append(fn)

    # 4. calibration_bias
    p = req.predictions
    if p is not None:
        cr, fn = _ran(CalibrationBiasCheck().run(predicted=p.predicted, outcomes=p.outcomes))
    else:
        cr, fn = _skip("calibration_bias", "no `predictions` block provided")
    results.append(cr)
    if fn is not None:
        findings.append(fn)

    # 5. overfit_flags
    m = req.metrics
    if m is not None:
        cr, fn = _ran(OverfitFlagsCheck().run(
            in_sample=m.in_sample, holdout=m.holdout, n_cells_scanned=m.n_cells_scanned,
            bounded=m.bounded, abs_alarm=m.abs_alarm, metric=m.metric))
    else:
        cr, fn = _skip("overfit_flags", "no `metrics` block provided")
    results.append(cr)
    if fn is not None:
        findings.append(fn)

    verdict = _verdict(findings)
    counts = {
        "pass": sum(1 for c in results if c.status == "PASS"),
        "warn": sum(1 for c in results if c.status == "WARN"),
        "fail": sum(1 for c in results if c.status == "FAIL"),
        "skipped": sum(1 for c in results if c.status == "SKIPPED"),
    }
    return AuditResponse(
        target=req.target,
        trust_score=_trust_score(findings),
        verdict=verdict,
        summary=_summary(counts, verdict),
        counts=counts,
        checks=results,
    )


def _verdict(findings: list[Finding]) -> str:
    if not findings:
        return "INCONCLUSIVE"
    if any(f.severity is Severity.FAIL for f in findings):
        return "NOT_TRUSTWORTHY"
    if any(f.severity is Severity.WARN for f in findings):
        return "INCONCLUSIVE"
    return "TRUSTWORTHY"


def _trust_score(findings: list[Finding]) -> int:
    fails = sum(1 for f in findings if f.severity is Severity.FAIL)
    warns = sum(1 for f in findings if f.severity is Severity.WARN)
    if not findings:
        return 50
    if fails:
        return max(0, 40 - 12 * (fails - 1) - 3 * warns)
    if warns:
        return max(45, 70 - 10 * warns)
    return 100


_PHRASE = {
    "TRUSTWORTHY": "trustworthy",
    "INCONCLUSIVE": "inconclusive",
    "NOT_TRUSTWORTHY": "not trustworthy",
}


def _summary(counts: dict[str, int], verdict: str) -> str:
    parts = []
    if counts["fail"]:
        parts.append(f"{counts['fail']} failed")
    if counts["warn"]:
        parts.append(f"{counts['warn']} warned")
    if counts["pass"]:
        parts.append(f"{counts['pass']} passed")
    if counts["skipped"]:
        parts.append(f"{counts['skipped']} skipped")
    ran = counts["pass"] + counts["warn"] + counts["fail"]
    lead = ", ".join(parts) if parts else "no checks"
    tail = "no checks ran" if ran == 0 else _PHRASE[verdict]
    return f"{lead} — {tail}."
