# Verification & Honest Limits

This service went through a pre-deploy adversarial audit (a fresh read-only red-team pass, grader ≠ builder) plus several fix + re-review rounds. This document records what was found, what was fixed, and the honest limits that remain. Guardrail throughout: **no test was ever weakened to pass** — every finding was either fixed in code or recorded here as a limit.

## Test & build status
- `pytest`: **204 passing** — unit + API + `tests/test_adversarial.py` (adversarial regression battery) + chi-square scipy-parity.
- Pure-Python chi-square matches `scipy.stats.chi2.sf` to ≤1e-9 (parity test); no scipy/numpy at runtime.
- Docker image builds clean; container runs as non-root `appuser`; `HEALTHCHECK` reports healthy; `$PORT` honored; runtime deps are `fastapi`/`uvicorn`/`pydantic` only.
- Determinism: identical input → identical verdict/score/order (verified).

## The core invariant: "absence of evidence → never green"
A trust auditor that can be tricked into certifying trust on no real evidence is worthless. The adversarial pass (and follow-up fuzz sweeps) found the aggregator violated this in several ways; all were fixed:

| # | Fake-green found | Fix |
|---|---|---|
| 1 | A single passing check → `TRUSTWORTHY`/100 while 4 checks were SKIPPED | Coverage gating: `TRUSTWORTHY` requires passing findings from **≥2 distinct input blocks** (`split`/`predictions`/`features`/`metrics`). |
| 2 | `split` alone produced 2 OK findings (temporal + group) → green | Coverage counts distinct input **blocks**, not raw findings — temporal & group both map to `split`. |
| 3 | `overfit` with `in_sample` but no `holdout` returned OK → green (incl. via `n_cells_scanned` 2–43 or `abs_alarm` param tricks) | A no-holdout overfit OK → SKIPPED; never a passing block (no out-of-sample evidence). Real red flags still WARN/FAIL. |
| 4 | A clean temporal/group split on 1–3 points (or 20 **padded duplicate** timestamps) counted as evidence | A temporal OK counts only with ≥20 **distinct** timestamps/side; a group OK only with ≥8 **distinct** entities/side. FAIL is never suppressed. |
| 5 | Near-perfect on BOTH train & holdout (`1.0/1.0`) → overfit gap-check blind → OK | Near-perfect-on-both (both ≥0.99, bounded) → WARN (leakage signature). |
| 6 | Empty / single-class predictions certified via calibration | Empty predictions → SKIPPED; single-class outcomes → SKIPPED (can't calibrate one class). |
| 7 | Calibration printed "well calibrated — ECE 0.200" (Hosmer-Lemeshow underpowered at small n) | ECE ceiling at the material floor (0.03): any OK-path calibration with ECE ≥ 0.03 → WARN, never certified. |

A final fuzz sweep of **245** thin/degenerate inputs (all single blocks and thin-block pairs, incl. padded-duplicate variants) returns **0** abstain-as-PASS fake-greens. The only reachable green from that sweep is the documented calibration-vs-discrimination limit below. Green remains reachable from ≥2 independent blocks of genuinely sufficient data.

## Robustness (public endpoint)
The service never returns a bare 500, never leaks a stack trace, never hangs, and never emits invalid-JSON tokens. Adversarial inputs are rejected with a helpful `400 {error,message,field}`:
- Non-finite numbers (`NaN`/`±Infinity`) in any float field → 400.
- `predicted` outside [0,1]; `outcomes` not in {0,1} → 400.
- Bool where a metric number is expected → 400.
- Oversized inputs (DoS): any array > 100,000 elements, > 1,000 feature columns, or > 2,000,000 feature cells → 400.
- Malformed JSON / wrong types / unknown fields → 400 (422 remapped).

Absent blocks are SKIPPED (200); only present-but-broken blocks 400. Empty body → 200, all SKIPPED, INCONCLUSIVE.

## Honest limits (documented, not "fixed")
These are inherent to what the statistical checks measure. The service is transparent about them via per-check SKIPPED/WARN status and `detail` strings; it does not paper over them.

1. **Trust ≠ usefulness/discrimination.** The checks probe specific *failure modes* (leakage, overfit gap, calibration). A model can pass every probed mode and still be useless. Example: a constant predictor at the base rate is genuinely *calibrated*, so a `predictions` block of constant `0.5` passes calibration; paired with another passing block it can reach `TRUSTWORTHY`. The verdict certifies "no probed failure mode fired across ≥2 dimensions," **NOT** "this is a good model." Callers wanting discrimination guarantees should supply `features` (target-leakage) and real, varied predictions.
2. **Overfit is gap-based.** `overfit_flags` detects in-sample≫holdout gaps and implausible values; it cannot see leakage that makes the holdout look genuinely good (that is what the `temporal`/`group`/`target` leakage checks are for, and they need the actual data, not just metrics). Near-perfect-on-both is flagged (WARN) as a heuristic; subtler leakage yielding a plausible holdout is only caught when leakage data is supplied.
3. **Calibration at small n.** Hosmer-Lemeshow is underpowered on small holdouts. The service errs safe: <50 rows → WARN (not certified); ECE ≥ 0.03 → WARN even if not statistically significant. Genuinely-calibrated small samples may therefore be reported INCONCLUSIVE rather than green — deliberate caution for a trust product.
4. **Sample-size floors are conservative but fixed.** target ≥30 rows (both classes), calibration ≥50 rows, temporal ≥20 distinct timestamps/side, group ≥8 distinct entities/side. Data meeting these floors yields correspondingly modest evidence; each check's `detail` discloses the sample it saw.
5. **DoS caps are application-level.** Element/column/cell caps bound per-request CPU; a full defense (request body-size limit, rate limiting, auth) is the deployment platform's responsibility.
6. **No pinned base-image digest.** `python:3.12-slim` is pinned by tag, not digest — a minor supply-chain consideration for a demo image.

## Scope note
This is **Pass 1** (the service + build, pre-deploy). **Pass 2** — a live deployed endpoint plus a SKILL.md-only agent that calls the service blind — happens after deploy + SKILL.md are in place.
