"""Audit engine: validate the request, run the check for each present block,
skip absent blocks, and aggregate Findings into a verdict + trust score.

Verdict/score are lifted verbatim (in behavior) from Legibright's AuditReport,
computed over the checks that RAN only. SKIPPED = the input block is absent.
"""
from __future__ import annotations

import math

from .checks.base import Finding, Severity
from .checks.calibration_bias import CalibrationBiasCheck
from .checks.group_leakage import GroupLeakageCheck
from .checks.overfit_flags import OverfitFlagsCheck
from .checks.target_leakage import TargetLeakageCheck
from .checks.temporal_leakage import TemporalLeakageCheck
from .errors import InvalidInput
from .schemas import AuditRequest, AuditResponse, CheckResult

MAX_ARRAY_LEN = 100_000
MAX_FEATURE_COLUMNS = 1_000
MAX_FEATURE_CELLS = 2_000_000
_ECE_CEILING = 0.03  # = calibration_bias.ece_material; never certify OK above the material floor
MIN_SPLIT_ROWS = 20       # temporal: a clean cut on fewer points is not evidence
MIN_GROUP_ENTITIES = 8    # group: too few distinct entities can't certify "no overlap"
_NEAR_PERFECT_BOTH = 0.99  # near-perfect on BOTH train & holdout = leakage signature

_STATUS = {Severity.OK: "PASS", Severity.WARN: "WARN", Severity.FAIL: "FAIL"}


def _require_len(name: str, values) -> None:
    if len(values) > MAX_ARRAY_LEN:
        raise InvalidInput(
            f"{name} has {len(values)} items, exceeding the {MAX_ARRAY_LEN}-element limit.", field=name)


def _require_finite(name: str, values) -> None:
    for i, v in enumerate(values):
        if not math.isfinite(v):
            raise InvalidInput(
                f"{name} contains a non-finite value (NaN/Infinity) at index {i}.", field=name)


def _validate(req: AuditRequest) -> None:
    """Present-but-broken blocks → InvalidInput (→ HTTP 400). Absent blocks are fine."""
    s = req.split
    if s is not None:
        if (s.train_ts is None) != (s.test_ts is None):
            missing = "test_ts" if s.train_ts is not None else "train_ts"
            raise InvalidInput(
                f"split.{missing} is required when its counterpart is provided — "
                "temporal leakage needs both train_ts and test_ts.",
                field=f"split.{missing}")
        if (s.train_groups is None) != (s.test_groups is None):
            missing = "test_groups" if s.train_groups is not None else "train_groups"
            raise InvalidInput(
                f"split.{missing} is required when its counterpart is provided — "
                "group leakage needs both train_groups and test_groups.",
                field=f"split.{missing}")
        for nm, arr in (("split.train_ts", s.train_ts), ("split.test_ts", s.test_ts)):
            if arr is not None:
                _require_len(nm, arr)
                _require_finite(nm, arr)
        for nm, arr in (("split.train_groups", s.train_groups), ("split.test_groups", s.test_groups)):
            if arr is not None:
                _require_len(nm, arr)

    p = req.predictions
    if p is not None:
        if len(p.predicted) != len(p.outcomes):
            raise InvalidInput(
                f"predictions.predicted has {len(p.predicted)} items but predictions.outcomes "
                f"has {len(p.outcomes)} — they must be equal length.",
                field="predictions.outcomes")
        _require_len("predictions.predicted", p.predicted)
        _require_finite("predictions.predicted", p.predicted)
        for i, v in enumerate(p.predicted):
            if not (0.0 <= v <= 1.0):
                raise InvalidInput(
                    f"predictions.predicted[{i}]={v} is outside [0,1] — "
                    "predicted probabilities must be in [0,1].",
                    field="predictions.predicted")
        for i, v in enumerate(p.outcomes):
            if v not in (0, 1):
                raise InvalidInput(
                    f"predictions.outcomes[{i}]={v} is not 0 or 1 — outcomes must be binary labels.",
                    field="predictions.outcomes")

    f = req.features
    if f is not None:
        if not f.cols:
            raise InvalidInput("features.cols must contain at least one column.", field="features.cols")
        if len(f.cols) > MAX_FEATURE_COLUMNS:
            raise InvalidInput(
                f"features.cols has {len(f.cols)} columns, exceeding the "
                f"{MAX_FEATURE_COLUMNS}-column limit.", field="features.cols")
        total = 0
        for name, vals in f.cols.items():
            if len(vals) != len(f.outcomes):
                raise InvalidInput(
                    f"features.cols['{name}'] has {len(vals)} items but features.outcomes "
                    f"has {len(f.outcomes)} — every column must match outcomes length.",
                    field=f"features.cols.{name}")
            _require_finite(f"features.cols.{name}", vals)
            total += len(vals)
        if total > MAX_FEATURE_CELLS:
            raise InvalidInput(
                f"features has {total} total cells, exceeding the {MAX_FEATURE_CELLS}-cell limit.",
                field="features.cols")
        for i, v in enumerate(f.outcomes):
            if v not in (0, 1):
                raise InvalidInput(
                    f"features.outcomes[{i}]={v} is not 0 or 1 — outcomes must be binary labels.",
                    field="features.outcomes")

    m = req.metrics
    if m is not None:
        for nm, v in (("metrics.in_sample", m.in_sample),
                      ("metrics.holdout", m.holdout),
                      ("metrics.abs_alarm", m.abs_alarm)):
            if v is not None and not math.isfinite(v):
                raise InvalidInput(
                    f"{nm} is non-finite (NaN/Infinity) — must be a finite number.", field=nm)


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


def _enforce_ece_ceiling(finding: Finding) -> Finding:
    """Honesty gate: a large ECE must never be certified OK, even when Hosmer-Lemeshow is
    non-significant (underpowered at small n). Downgrade OK→WARN so 'well calibrated' is
    never printed alongside a materially large calibration error."""
    if finding.severity is Severity.OK:
        ece = finding.metrics.get("ece")
        if ece is not None and ece >= _ECE_CEILING:
            return Finding(
                finding.check, Severity.WARN,
                f"calibration uncertain — ECE {ece:.3f} ≥ {_ECE_CEILING} yet HL not significant "
                f"(likely underpowered); NOT certified well-calibrated",
                detail=finding.detail, metrics=finding.metrics, suggested_tags=["audit-warn"])
    return finding


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
            finding = TemporalLeakageCheck().run(train_ts=s.train_ts, test_ts=s.test_ts)
            if finding.severity is Severity.OK and (
                    len(set(s.train_ts)) < MIN_SPLIT_ROWS or len(set(s.test_ts)) < MIN_SPLIT_ROWS):
                cr, fn = _skip("temporal_leakage",
                               f"too few distinct timestamps to certify a clean split (need "
                               f"≥{MIN_SPLIT_ROWS} per side) — a clean cut on tiny/padded data is "
                               "not evidence")
            else:
                cr, fn = _ran(finding)
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
            finding = GroupLeakageCheck().run(
                train_groups=s.train_groups, test_groups=s.test_groups, entity=s.entity)
            if finding.severity is Severity.OK and (
                    len(set(s.train_groups)) < MIN_GROUP_ENTITIES
                    or len(set(s.test_groups)) < MIN_GROUP_ENTITIES):
                cr, fn = _skip("group_leakage",
                               f"too few distinct entities to certify no overlap "
                               f"(need ≥{MIN_GROUP_ENTITIES} per side)")
            else:
                cr, fn = _ran(finding)
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
        if not p.predicted:
            cr, fn = _skip("calibration_bias", "predictions arrays are empty — nothing to calibrate")
        elif len(set(p.outcomes)) < 2:
            cr, fn = _skip("calibration_bias",
                           "calibration needs both outcome classes (0 and 1) present — "
                           "cannot certify from a single class")
        else:
            finding = _enforce_ece_ceiling(
                CalibrationBiasCheck().run(predicted=p.predicted, outcomes=p.outcomes))
            cr, fn = _ran(finding)
    else:
        cr, fn = _skip("calibration_bias", "no `predictions` block provided")
    results.append(cr)
    if fn is not None:
        findings.append(fn)

    # 5. overfit_flags
    m = req.metrics
    if m is not None:
        finding = OverfitFlagsCheck().run(
            in_sample=m.in_sample, holdout=m.holdout, n_cells_scanned=m.n_cells_scanned,
            bounded=m.bounded, abs_alarm=m.abs_alarm, metric=m.metric)
        if m.holdout is None and finding.severity is Severity.OK:
            # No holdout ⇒ no out-of-sample evidence. A clean run here only means "no other red
            # flag fired" (abs_alarm / multiple-testing), NOT that the model generalizes. It must
            # never count as a passing dimension. (abs_alarm/n_cells can still WARN/FAIL below.)
            cr, fn = _skip("overfit_flags",
                           "overfit cannot certify generalization without a holdout — "
                           "in_sample alone is not out-of-sample evidence")
        elif (finding.severity is Severity.OK and m.bounded and m.holdout is not None
              and m.in_sample >= _NEAR_PERFECT_BOTH and m.holdout >= _NEAR_PERFECT_BOTH):
            cr, fn = _ran(Finding(
                finding.check, Severity.WARN,
                f"near-perfect on BOTH train ({m.in_sample:.3f}) and holdout ({m.holdout:.3f}) — "
                "implausible without leakage; a gap-based check cannot certify this clean",
                detail=finding.detail, metrics=finding.metrics, suggested_tags=["audit-warn"]))
        else:
            cr, fn = _ran(finding)
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


_CHECK_BLOCK = {
    "temporal_leakage": "split",
    "group_leakage": "split",
    "target_leakage": "features",
    "calibration_bias": "predictions",
    "overfit_flags": "metrics",
}


def _passing_blocks(findings: list[Finding]) -> set[str]:
    """Distinct INPUT BLOCKS that produced a passing (OK) finding. temporal+group both map to
    `split`, so one split block is a single evidence source, not two."""
    return {_CHECK_BLOCK[f.check] for f in findings if f.severity is Severity.OK}


def _verdict(findings: list[Finding]) -> str:
    if not findings:
        return "INCONCLUSIVE"
    if any(f.severity is Severity.FAIL for f in findings):
        return "NOT_TRUSTWORTHY"
    if any(f.severity is Severity.WARN for f in findings):
        return "INCONCLUSIVE"
    # all ran-checks passed: certifying trust needs corroboration from >=2 INDEPENDENT input
    # blocks (a single input source — e.g. `split`, which drives both temporal & group — is
    # not enough). "absence of evidence → never green."
    if len(_passing_blocks(findings)) >= 2:
        return "TRUSTWORTHY"
    return "INCONCLUSIVE"


def _trust_score(findings: list[Finding]) -> int:
    fails = sum(1 for f in findings if f.severity is Severity.FAIL)
    warns = sum(1 for f in findings if f.severity is Severity.WARN)
    if not findings:
        return 50
    if fails:
        return max(0, 40 - 12 * (fails - 1) - 3 * warns)
    if warns:
        return max(45, 70 - 10 * warns)
    # all passed
    if len(_passing_blocks(findings)) >= 2:
        return 100
    return 60  # passing evidence from a single input block — INCONCLUSIVE band


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
    if ran == 0:
        tail = "no checks ran"
    elif verdict == "INCONCLUSIVE" and counts["fail"] == 0 and counts["warn"] == 0:
        tail = "insufficient coverage to certify trust (need passing checks from ≥2 independent inputs)"
    else:
        tail = _PHRASE[verdict]
    return f"{lead} — {tail}."
