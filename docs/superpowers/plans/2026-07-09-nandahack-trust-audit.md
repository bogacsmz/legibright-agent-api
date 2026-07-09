# NandaHack Trust Audit API — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stateless FastAPI service that audits statistical honesty (leakage, overfit, calibration) of a model/backtest claim and returns an agent-callable trust verdict.

**Architecture:** A thin HTTP + aggregation layer wraps a verbatim copy of Legibright's five pure "honest-metrics" checks. `POST /audit` takes a flexible union of input blocks, runs the check for each present block, skips absent ones, and aggregates Findings into a `trust_score` + `verdict`. No DB, no auth, no state.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, uvicorn. Pure-Python statistics (no scipy at runtime).

## Global Constraints

- Standalone repo at `~/Claude/Projects/nandahack/`. NEVER import from or modify the Legibright/hackathon/DataHub repos. Check files are **copied**, not referenced at runtime.
- Stateless: no database, no auth, no persistence, no sessions.
- Runtime deps minimal: `fastapi`, `uvicorn[standard]`, `pydantic` ONLY. scipy is a **test-only** dependency.
- Never an uncaught 500: caller-input problems → HTTP 400 with envelope `{"error","message","field"}`; FastAPI's 422 is remapped to 400; genuine internal errors return a clean JSON 500, never a stack trace.
- Absent input block → check SKIPPED (200). Present-but-broken block → helpful 400.
- Response ALWAYS lists all five checks (absent ones as SKIPPED).
- Verdict/score computed over checks that RAN only. Bands: TRUSTWORTHY 71-100 · INCONCLUSIVE 45-70 · NOT_TRUSTWORTHY 0-40. No check ran → INCONCLUSIVE / 50.
- Apache-2.0 LICENSE.
- Source of the check files to copy:
  - `~/Claude/Projects/hackathon/src/trust_layer/checks/base.py`
  - `~/Claude/Projects/hackathon/src/trust_layer/checks/honest_metrics/{temporal_leakage,target_leakage,group_leakage,overfit_flags,calibration_bias}.py`

---

### Task 1: Scaffolding + copy the check core

**Files:**
- Create: `app/__init__.py`, `app/checks/__init__.py`
- Create (by copy): `app/checks/base.py`, `app/checks/temporal_leakage.py`, `app/checks/target_leakage.py`, `app/checks/group_leakage.py`, `app/checks/overfit_flags.py`, `app/checks/calibration_bias.py`
- Create: `requirements.txt`, `requirements-dev.txt`, `.gitignore`, `LICENSE`
- Test: `tests/__init__.py`, `tests/test_checks_import.py`

**Interfaces:**
- Produces: `app.checks.base.{Finding, Severity, Verdict, Check}`; check classes `TemporalLeakageCheck`, `TargetLeakageCheck`, `GroupLeakageCheck`, `OverfitFlagsCheck`, `CalibrationBiasCheck`, each with `.run(...) -> Finding`. `Severity` has members `OK/WARN/FAIL`; `Finding` has `.check, .severity, .headline, .detail, .metrics`.

- [ ] **Step 1: Copy the check files verbatim**

```bash
cd ~/Claude/Projects/nandahack
mkdir -p app/checks tests
SRC=~/Claude/Projects/hackathon/src/trust_layer/checks
cp "$SRC/base.py" app/checks/base.py
for f in temporal_leakage target_leakage group_leakage overfit_flags calibration_bias; do
  cp "$SRC/honest_metrics/$f.py" "app/checks/$f.py"
done
```

- [ ] **Step 2: Fix the relative import (checks now sit beside base.py, not one level below)**

The originals live in `checks/honest_metrics/` and import `from ..base import ...`. Flattened into `app/checks/`, that must become `from .base import ...`.

```bash
cd ~/Claude/Projects/nandahack
sed -i '' 's/from \.\.base import/from .base import/' \
  app/checks/temporal_leakage.py app/checks/target_leakage.py \
  app/checks/group_leakage.py app/checks/overfit_flags.py app/checks/calibration_bias.py
grep -rn "\.\.base" app/checks/ && echo "STILL HAS ..base — FIX" || echo "imports OK"
```
Expected: `imports OK`

- [ ] **Step 3: Package markers**

```bash
cd ~/Claude/Projects/nandahack
printf '' > app/__init__.py
printf '' > app/checks/__init__.py
printf '' > tests/__init__.py
```

- [ ] **Step 4: requirements files**

Create `requirements.txt`:
```
fastapi==0.115.6
uvicorn[standard]==0.34.0
pydantic==2.10.5
```

Create `requirements-dev.txt`:
```
-r requirements.txt
pytest==8.3.4
httpx==0.28.1
scipy==1.15.1
```
(If a pin fails to resolve on install, use the nearest available release and record it.)

- [ ] **Step 5: `.gitignore` and `LICENSE`**

Create `.gitignore`:
```
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/
*.egg-info/
```

Create `LICENSE`: full Apache License 2.0 text.
```bash
cd ~/Claude/Projects/nandahack
curl -fsSL https://www.apache.org/licenses/LICENSE-2.0.txt -o LICENSE
head -1 LICENSE   # -> "                                 Apache License"
```

- [ ] **Step 6: Install deps**

```bash
cd ~/Claude/Projects/nandahack
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
```
Expected: installs without error.

- [ ] **Step 7: Write the import smoke test**

Create `tests/test_checks_import.py`:
```python
from app.checks.base import Finding, Severity, Verdict
from app.checks.temporal_leakage import TemporalLeakageCheck
from app.checks.target_leakage import TargetLeakageCheck
from app.checks.group_leakage import GroupLeakageCheck
from app.checks.overfit_flags import OverfitFlagsCheck
from app.checks.calibration_bias import CalibrationBiasCheck


def test_severity_members():
    assert {s.value for s in Severity} == {"OK", "WARN", "FAIL"}


def test_temporal_fail_and_ok():
    fail = TemporalLeakageCheck().run(train_ts=[1, 2, 3], test_ts=[2, 3, 4])
    ok = TemporalLeakageCheck().run(train_ts=[1, 2, 3], test_ts=[4, 5, 6])
    assert fail.severity is Severity.FAIL
    assert ok.severity is Severity.OK


def test_overfit_hero_fail():
    f = OverfitFlagsCheck().run(in_sample=0.99, holdout=0.74)
    assert f.severity is Severity.FAIL
```

- [ ] **Step 8: Run the smoke test**

Run: `cd ~/Claude/Projects/nandahack && . .venv/bin/activate && python -m pytest tests/test_checks_import.py -v`
Expected: 3 passed.

- [ ] **Step 9: Commit**

```bash
cd ~/Claude/Projects/nandahack
git add app tests requirements.txt requirements-dev.txt .gitignore LICENSE
git commit -m "feat: scaffold repo and copy honest-metrics check core"
```

---

### Task 2: Correct pure-Python chi-square (drop scipy from runtime)

**Files:**
- Modify: `app/checks/calibration_bias.py` (replace the `_chi2_sf` function; add two helpers)
- Test: `tests/test_chi2.py`

**Interfaces:**
- Produces: `app.checks.calibration_bias._chi2_sf(x: float, df: int) -> float` — exact chi-square survival function, no scipy import.

- [ ] **Step 1: Write the failing parity test**

Create `tests/test_chi2.py`:
```python
import math
import pytest
from scipy.stats import chi2  # TEST-ONLY dependency
from app.checks.calibration_bias import _chi2_sf


@pytest.mark.parametrize("df", list(range(1, 13)))
@pytest.mark.parametrize("x", [0.0, 0.1, 0.5, 1.0, 2.0, 3.5, 5.0, 8.0, 12.0, 20.0, 30.0, 40.0])
def test_chi2_sf_matches_scipy(df, x):
    got = _chi2_sf(x, df)
    ref = float(chi2.sf(x, df))
    assert abs(got - ref) <= 1e-9, f"df={df} x={x}: {got} vs {ref}"
    if ref > 1e-12:
        assert abs(got - ref) / ref <= 1e-6


def test_chi2_sf_edges():
    assert _chi2_sf(0.0, 4) == 1.0
    assert _chi2_sf(-1.0, 4) == 1.0
    assert 0.0 < _chi2_sf(50.0, 3) < 1e-8
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ~/Claude/Projects/nandahack && . .venv/bin/activate && python -m pytest tests/test_chi2.py -q`
Expected: FAIL — current `_chi2_sf` uses the crude Wilson-Hilferty fallback (import scipy is absent at runtime path only inside the function), so upper-tail values miss the 1e-9 tolerance.

- [ ] **Step 3: Replace `_chi2_sf` with the exact implementation**

In `app/checks/calibration_bias.py`, delete the existing `_chi2_sf` function (the one that tries `from scipy.stats import chi2` with a Wilson-Hilferty fallback) and replace it with:

```python
def _chi2_sf(x, df):
    """Exact chi-square upper-tail survival function, pure Python.

    chi2.sf(x, df) == Q(df/2, x/2), the regularized upper incomplete gamma.
    Matches scipy.stats.chi2.sf to ~machine precision. No scipy at runtime.
    """
    if x <= 0:
        return 1.0
    return _gammq(df / 2.0, x / 2.0)


def _gammq(a, x):
    """Regularized upper incomplete gamma Q(a, x) (Numerical Recipes gammq)."""
    if x < 0.0 or a <= 0.0:
        raise ValueError("bad args to _gammq")
    if x == 0.0:
        return 1.0
    if x < a + 1.0:
        return 1.0 - _gser(a, x)          # lower branch via series
    return _gcf(a, x)                     # upper branch via continued fraction


def _gser(a, x):
    """Lower regularized incomplete gamma P(a, x) via series expansion."""
    gln = math.lgamma(a)
    ap = a
    total = 1.0 / a
    delta = total
    for _ in range(1000):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * 1e-16:
            break
    return total * math.exp(-x + a * math.log(x) - gln)


def _gcf(a, x):
    """Upper regularized incomplete gamma Q(a, x) via the Lentz continued fraction."""
    gln = math.lgamma(a)
    tiny = 1e-30
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-16:
            break
    return math.exp(-x + a * math.log(x) - gln) * h
```

Ensure `import math` is present at the top of `calibration_bias.py` (it is imported inside the old fallback; move it to module level). Confirm no `from scipy` remains:
```bash
grep -n "scipy" app/checks/calibration_bias.py && echo "REMOVE scipy" || echo "no scipy"
grep -n "^import math" app/checks/calibration_bias.py || echo "ADD module-level import math"
```
Expected: `no scipy`, and module-level `import math` present.

- [ ] **Step 4: Run the parity test**

Run: `cd ~/Claude/Projects/nandahack && . .venv/bin/activate && python -m pytest tests/test_chi2.py -q`
Expected: all parametrized cases passed.

- [ ] **Step 5: Re-run the whole suite (calibration path still works)**

Run: `cd ~/Claude/Projects/nandahack && . .venv/bin/activate && python -m pytest -q`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
cd ~/Claude/Projects/nandahack
git add app/checks/calibration_bias.py tests/test_chi2.py
git commit -m "feat: exact pure-Python chi-square with scipy parity test"
```

---

### Task 3: Request/response schemas + error type

**Files:**
- Create: `app/errors.py`
- Create: `app/schemas.py`
- Test: `tests/test_schemas.py`

**Interfaces:**
- Produces: `app.errors.InvalidInput(message: str, field: str | None)` (Exception with `.message`, `.field`).
- Produces request models `AuditRequest` with optional `.split, .predictions, .features, .metrics` and `.target: str`; nested `SplitBlock, PredictionsBlock, FeaturesBlock, MetricsBlock`.
- Produces response models `CheckResult` and `AuditResponse`.

- [ ] **Step 1: Write the failing schema test**

Create `tests/test_schemas.py`:
```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ~/Claude/Projects/nandahack && . .venv/bin/activate && python -m pytest tests/test_schemas.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas'`.

- [ ] **Step 3: Implement `app/errors.py`**

```python
"""Service-level input error → mapped to a helpful HTTP 400."""
from __future__ import annotations


class InvalidInput(Exception):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field
```

- [ ] **Step 4: Implement `app/schemas.py`**

```python
"""Pydantic request/response models for the Trust Audit API.

Types only. Cross-field/semantic validation (pairing, equal-length) lives in
app/audit.py so it can raise InvalidInput with precise messages.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


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


class AuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = "unnamed"
    split: SplitBlock | None = None
    predictions: PredictionsBlock | None = None
    features: FeaturesBlock | None = None
    metrics: MetricsBlock | None = None


class CheckResult(BaseModel):
    check: str
    status: str  # PASS | WARN | FAIL | SKIPPED
    headline: str | None = None
    detail: str | None = None
    metrics: dict[str, Any] | None = None
    reason: str | None = None


class AuditResponse(BaseModel):
    target: str
    trust_score: int
    verdict: str
    summary: str
    counts: dict[str, int]
    checks: list[CheckResult]
```

- [ ] **Step 5: Run the schema test**

Run: `cd ~/Claude/Projects/nandahack && . .venv/bin/activate && python -m pytest tests/test_schemas.py -q`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
cd ~/Claude/Projects/nandahack
git add app/errors.py app/schemas.py tests/test_schemas.py
git commit -m "feat: request/response schemas and InvalidInput error"
```

---

### Task 4: Audit engine — validation, block→check mapping, aggregation

**Files:**
- Create: `app/audit.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `AuditRequest` (Task 3); the five check classes and `Severity` (Task 1).
- Produces: `app.audit.run_audit(req: AuditRequest) -> AuditResponse`. Raises `InvalidInput` on present-but-broken blocks. The five checks always appear in this fixed order: `temporal_leakage, group_leakage, target_leakage, calibration_bias, overfit_flags`. SKIPPED means the input block is absent.

- [ ] **Step 1: Write the failing engine tests**

Create `tests/test_engine.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ~/Claude/Projects/nandahack && . .venv/bin/activate && python -m pytest tests/test_engine.py -q`
Expected: FAIL — `No module named 'app.audit'`.

- [ ] **Step 3: Implement `app/audit.py`**

```python
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
        cr, fn = _ran(TemporalLeakageCheck().run(train_ts=s.train_ts, test_ts=s.test_ts))
    else:
        cr, fn = _skip("temporal_leakage", "no `split.train_ts`/`split.test_ts` provided")
    results.append(cr)
    if fn is not None:
        findings.append(fn)

    # 2. group_leakage
    if s is not None and s.train_groups is not None and s.test_groups is not None:
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
```

- [ ] **Step 4: Run the engine tests**

Run: `cd ~/Claude/Projects/nandahack && . .venv/bin/activate && python -m pytest tests/test_engine.py -q`
Expected: 7 passed.

- [ ] **Step 5: Run the full suite**

Run: `cd ~/Claude/Projects/nandahack && . .venv/bin/activate && python -m pytest -q`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
cd ~/Claude/Projects/nandahack
git add app/audit.py tests/test_engine.py
git commit -m "feat: audit engine — validation, block mapping, verdict/score"
```

---

### Task 5: FastAPI app — endpoints + error handlers

**Files:**
- Create: `app/main.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `run_audit`, `AuditRequest`, `AuditResponse`, `InvalidInput`.
- Produces: `app.main.app` (FastAPI). Routes: `GET /health`, `GET /`, `POST /audit`.

- [ ] **Step 1: Write the failing API tests**

Create `tests/test_api.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ~/Claude/Projects/nandahack && . .venv/bin/activate && python -m pytest tests/test_api.py -q`
Expected: FAIL — `No module named 'app.main'`.

- [ ] **Step 3: Implement `app/main.py`**

```python
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
                 "message": "an internal error occurred while auditing"},
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
```

- [ ] **Step 4: Run the API tests**

Run: `cd ~/Claude/Projects/nandahack && . .venv/bin/activate && python -m pytest tests/test_api.py -q`
Expected: 7 passed.

Note: if `test_unexpected_handler` interference is suspected, the broad `Exception` handler must NOT catch `RequestValidationError`/`InvalidInput` — FastAPI dispatches the most specific handler first, so those return 400, not 500.

- [ ] **Step 5: Run full suite**

Run: `cd ~/Claude/Projects/nandahack && . .venv/bin/activate && python -m pytest -q`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
cd ~/Claude/Projects/nandahack
git add app/main.py tests/test_api.py
git commit -m "feat: FastAPI app with endpoints and 400/500 error handlers"
```

---

### Task 6: Live server verification + full-coverage per-check tests

**Files:**
- Modify: `tests/test_api.py` (add PASS/FAIL per remaining check)
- Create: `docs/EXAMPLES.md` (real curl request/response pairs)

**Interfaces:**
- Consumes: everything above. No new production code — this task proves the deliverable end-to-end against a running server.

- [ ] **Step 1: Add per-check PASS/FAIL coverage tests**

Append to `tests/test_api.py`:
```python
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
        "split": {"train_ts": [1, 2, 3], "test_ts": [4, 5, 6]},
        "metrics": {"in_sample": 0.99, "holdout": 0.74},
    })
    body = r.json()
    assert body["target"] == "model_x"
    assert body["verdict"] == "NOT_TRUSTWORTHY"  # overfit FAIL dominates
    by = {c["check"]: c for c in body["checks"]}
    assert by["temporal_leakage"]["status"] == "PASS"
    assert by["overfit_flags"]["status"] == "FAIL"
```

- [ ] **Step 2: Run the expanded suite**

Run: `cd ~/Claude/Projects/nandahack && . .venv/bin/activate && python -m pytest -q`
Expected: all passed.

- [ ] **Step 3: Boot the real server**

```bash
cd ~/Claude/Projects/nandahack && . .venv/bin/activate
uvicorn app.main:app --port 8000 &
sleep 2
```

- [ ] **Step 4: Exercise every endpoint with real curl and capture output**

```bash
curl -s http://localhost:8000/health; echo
curl -s http://localhost:8000/ | python -m json.tool | head -20
# hero: two numbers -> NOT_TRUSTWORTHY
curl -sX POST http://localhost:8000/audit -H 'content-type: application/json' \
  -d '{"metrics":{"in_sample":0.99,"holdout":0.74}}' | python -m json.tool
# leaky split
curl -sX POST http://localhost:8000/audit -H 'content-type: application/json' \
  -d '{"target":"backtest_v2","split":{"train_ts":[1,2,3],"test_ts":[2,3,4]}}' | python -m json.tool
# helpful 400
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/audit \
  -H 'content-type: application/json' -d '{"predictions":{"predicted":[0.1,0.2],"outcomes":[1]}}'
```
Expected: `{"status": "ok"}`; root JSON with 5 checks; hero verdict `NOT_TRUSTWORTHY`; leaky split `NOT_TRUSTWORTHY`; last call prints `400`.

- [ ] **Step 5: Stop the server**

```bash
kill %1 2>/dev/null || pkill -f "uvicorn app.main:app"
```

- [ ] **Step 6: Write `docs/EXAMPLES.md`**

Paste the REAL request/response pairs captured in Step 4 (verbatim JSON output), each under a heading: Health, Root, Minimal metrics (hero), Leaky split, Helpful 400. Do not hand-edit the JSON — use what the server returned.

- [ ] **Step 7: Commit**

```bash
cd ~/Claude/Projects/nandahack
git add tests/test_api.py docs/EXAMPLES.md
git commit -m "test: per-check API coverage + verified curl examples"
```

---

### Task 7: Deploy artifacts + README

**Files:**
- Create: `Dockerfile`, `Procfile`, `.dockerignore`, `README.md`

**Interfaces:**
- Consumes: the finished app. No production code changes.

- [ ] **Step 1: `Procfile`**

```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- [ ] **Step 2: `.dockerignore`**

```
.git
.venv
venv
__pycache__
*.pyc
.pytest_cache
tests
docs
```

- [ ] **Step 3: `Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

- [ ] **Step 4: Build and smoke-test the image**

```bash
cd ~/Claude/Projects/nandahack
docker build -t trust-audit-api . && \
docker run -d -p 8010:8000 --name ta trust-audit-api && sleep 3 && \
curl -s http://localhost:8010/health; echo && \
curl -sX POST http://localhost:8010/audit -H 'content-type: application/json' \
  -d '{"metrics":{"in_sample":0.99,"holdout":0.74}}' | python -m json.tool | head -8
docker rm -f ta
```
Expected: `{"status": "ok"}` and a `NOT_TRUSTWORTHY` verdict from the container. (If Docker daemon is not running, start Docker Desktop: `open -a Docker`, wait, retry. If Docker is unavailable, note it and rely on the Task 6 uvicorn verification.)

- [ ] **Step 5: `README.md` — hero curl FIRST**

Create `README.md` with this order:
1. Title + one-line description.
2. **Quickstart — the two-number hero call FIRST**, exactly:
   ````markdown
   ```bash
   curl -sX POST http://localhost:8000/audit -H 'content-type: application/json' \
     -d '{"metrics":{"in_sample":0.99,"holdout":0.74}}'
   ```
   ````
   followed by the real response (from `docs/EXAMPLES.md`) showing `NOT_TRUSTWORTHY`.
3. **Run locally:** `pip install -r requirements.txt` then `uvicorn app.main:app --reload`.
4. **Endpoints:** `POST /audit`, `GET /health`, `GET /` (one line each).
5. **Request schema:** the union blocks table (split / predictions / features / metrics → which check), copied from the spec §4.
6. **Response schema:** statuses PASS/WARN/FAIL/SKIPPED; verdict bands; `counts`; note that all five checks always appear.
7. **What each check catches:** the five-row table (from the spec §3).
8. **Errors:** the 400 envelope + one example.
9. **Deploy:** Docker (`docker build`/`run`), Procfile (Railway/Render), `$PORT`, `/health` healthcheck.
10. **License:** Apache-2.0.

- [ ] **Step 6: Full suite one more time**

Run: `cd ~/Claude/Projects/nandahack && . .venv/bin/activate && python -m pytest -q`
Expected: all passed.

- [ ] **Step 7: Commit**

```bash
cd ~/Claude/Projects/nandahack
git add Dockerfile Procfile .dockerignore README.md
git commit -m "feat: deploy artifacts (Docker/Procfile) and agent-first README"
```

---

## Deliverables recap

- Running service: `GET /`, `GET /health`, `POST /audit`.
- Endpoint schema + verified local curl request/response pairs (`docs/EXAMPLES.md`, README).
- `pytest` green across `test_checks_import`, `test_chi2` (scipy parity), `test_schemas`, `test_engine`, `test_api`.
- Apache-2.0 LICENSE.
- Deploy-ready: Dockerfile + Procfile + .dockerignore + pinned requirements, reads `$PORT`, `/health` healthcheck.
