# NandaHack — Trust Audit API — Design

- **Date:** 2026-07-09
- **Status:** Approved (design), pending spec review
- **Project dir:** `~/Claude/Projects/nandahack/` (standalone; the Legibright/DataHub repos are never imported or modified)

## 1. Goal

A stateless, agent-callable HTTP service that audits the statistical honesty of a
model/backtest claim and returns a trust verdict. It wraps a **verbatim copy** of
Legibright's five DataHub-free "honest-metrics" checks behind a tiny FastAPI layer.

The heart of the value (and the score) is **blind agent-callability**: an agent that
knows nothing but the URL can send whatever numbers it has and get an actionable
verdict back, with per-check status and a one-line summary.

### Non-goals (YAGNI)

- No database, no persistence, no auth, no sessions — fully stateless.
- No model training or metric *computation*. The service audits numbers the caller
  supplies; it does not fit models or derive `in_sample`/`holdout` itself.
- No DataHub integration, no write-back, no incidents/assertions/tags.
- No SKILL.md yet (explicitly deferred until the service is solid).

## 2. Architecture & layout

```
nandahack/
  app/
    __init__.py
    main.py            # FastAPI app: GET /, GET /health, POST /audit; error handlers
    schemas.py         # Pydantic request/response models + cross-field validation
    audit.py           # request blocks -> checks -> findings -> verdict/score
    checks/            # COPIED VERBATIM from Legibright (app/checks == source of truth)
      __init__.py
      base.py          # Finding, Severity, Verdict
      temporal_leakage.py
      target_leakage.py
      group_leakage.py
      overfit_flags.py
      calibration_bias.py
  tests/
    test_audit.py      # PASS/FAIL/SKIPPED per check, minimal-input, empty body, 400s, smoke
  requirements.txt     # pinned runtime deps
  requirements-dev.txt # pinned test deps
  Dockerfile
  Procfile
  .dockerignore
  .gitignore
  LICENSE              # Apache-2.0
  README.md            # minimal curl FIRST, then full reference
```

**Copy, don't import.** `app/checks/base.py` and the five check modules are copied
byte-for-byte from `~/Claude/Projects/hackathon/src/trust_layer/checks/{base.py,honest_metrics/*}`.
The service never reaches into the Legibright/hackathon repo at runtime. The verdict
(`compute_verdict`) and trust-score banding are lifted from that repo's `agent.py`
`AuditReport` into `app/audit.py` unchanged in behavior.

## 3. The five checks (what each catches / what it needs)

| check | input block | catches |
|---|---|---|
| `temporal_leakage` | `split.train_ts`, `split.test_ts` | training rows dated at/after the test cutoff — future leaks in; random split masquerading as walk-forward |
| `group_leakage` | `split.train_groups`, `split.test_groups` | the same entity in train and test — the model memorizes it, not the pattern |
| `target_leakage` | `features.cols`, `features.outcomes` | a single feature that almost perfectly predicts the label (encodes the outcome) |
| `calibration_bias` | `predictions.predicted`, `predictions.outcomes` | statistically-significant probability miscalibration a single score hides (Hosmer-Lemeshow, sample-size aware) |
| `overfit_flags` | `metrics.in_sample` (+`holdout`, `n_cells_scanned`) | too-good in-sample, near-perfect memorization, holdout collapse, multiple-testing luck |

These are pure functions over plain Python lists — no numpy/sklearn imports. Only
`calibration_bias` optionally uses scipy (see Dependencies).

## 4. Request schema — `POST /audit`

Flexible union. The caller supplies whichever blocks it has; each present block runs
its check, each absent block is SKIPPED. All blocks except `target` are optional.

```jsonc
{
  "target": "my_model_v3",              // optional label echoed back; default "unnamed"
  "split": {
    "train_ts":     [float, ...],       // temporal_leakage: both ts arrays required together
    "test_ts":      [float, ...],
    "train_groups": [any, ...],         // group_leakage: both group arrays required together
    "test_groups":  [any, ...],
    "entity":       "team"              // optional label for group messages; default "entity"
  },
  "predictions": {                       // calibration_bias
    "predicted": [float, ...],          // predicted probabilities in [0,1]
    "outcomes":  [int, ...]             // 0/1 labels, same length as predicted
  },
  "features": {                          // target_leakage
    "cols":     { "f1": [float, ...], "f2": [float, ...] },
    "outcomes": [int, ...]             // 0/1 labels, same length as each column
  },
  "metrics": {                           // overfit_flags
    "in_sample":       0.99,            // required if the metrics block is present
    "holdout":         0.74,            // optional
    "n_cells_scanned": 1,              // optional, default 1
    "bounded":         true,           // optional, default true (accuracy/R2/AUC)
    "abs_alarm":       null,           // optional, for unbounded ROI-like metrics
    "metric":          "accuracy"      // optional label; default "score"
  }
}
```

**Presence & pairing rules** (enforced in `schemas.py` / `audit.py`):

- A block absent entirely → its check(s) SKIPPED.
- `split` may contribute temporal, group, or both. `train_ts` and `test_ts` must be
  supplied together (one without the other → 400). Same for `train_groups`/`test_groups`.
- `predictions` present → both `predicted` and `outcomes` required, equal length, numeric.
- `features` present → `cols` non-empty and every column length equals `outcomes` length.
- `metrics` present → `in_sample` required (numeric).
- Blocks are self-contained: each carries its own `outcomes`; no cross-block reuse.
- **Minimal input is first-class:** `{"metrics":{"in_sample":0.99,"holdout":0.74}}` is a
  complete, valid request that returns an overfit-only verdict.

## 5. Validation & error contract

The forgiveness rule:

1. **Absent block → SKIPPED, HTTP 200.** Partial audits are normal.
2. **Present-but-broken block → HTTP 400** with a specific, actionable message. Broken ≠
   skipped: silently skipping a fumbled payload would mislead a blind agent.
3. **Never an uncaught 500.** FastAPI's `RequestValidationError` (422) is remapped to a
   **400** with a flattened, readable message. A genuine internal error is caught by a
   global handler and returned as a clean JSON body, never a stack trace.

Single error envelope for every 400:

```json
{
  "error": "invalid_input",
  "message": "predictions.predicted has 100 items but predictions.outcomes has 98 — they must be equal length.",
  "field": "predictions.outcomes"
}
```

`field` is best-effort (dotted path); `message` is always human-actionable.

## 6. Response schema — `POST /audit` (200)

The response **always lists all five checks** (absent ones as SKIPPED), so one blind
call reveals the full capability surface.

```jsonc
{
  "target": "my_model_v3",
  "trust_score": 37,                     // 0-100, banded to verdict (1 fail + 1 warn = 40 - 3)
  "verdict": "NOT_TRUSTWORTHY",          // TRUSTWORTHY | INCONCLUSIVE | NOT_TRUSTWORTHY
  "summary": "1 failed, 1 warned, 3 skipped — not trustworthy.",
  "counts": { "pass": 0, "warn": 1, "fail": 1, "skipped": 3 },
  "checks": [
    {
      "check": "temporal_leakage",
      "status": "FAIL",                  // PASS | WARN | FAIL | SKIPPED
      "headline": "TEMPORAL LEAKAGE — training data overlaps the test period",
      "detail": "201/1000 (20.1%) training rows are dated at/after the earliest test row ...",
      "metrics": { "leak_ratio": 0.201, "train_max": 1699999999, "test_min": 1690000000 }
    },
    {
      "check": "target_leakage",
      "status": "SKIPPED",
      "reason": "no `features` block provided"
    }
    // ... always all five ...
  ]
}
```

Status mapping: `PASS = Severity.OK`, `WARN`, `FAIL` from the Finding; `SKIPPED` is
service-level (block absent, or the check declined for too-little-data with a `reason`).

### Verdict & score (lifted verbatim, computed over checks that RAN only)

- Any FAIL → `NOT_TRUSTWORTHY`; else any WARN → `INCONCLUSIVE`; else all PASS → `TRUSTWORTHY`.
- No check ran (all SKIPPED) → `INCONCLUSIVE`, `trust_score = 50` (absence of evidence is never green).
- Bands: `TRUSTWORTHY 71-100 · INCONCLUSIVE 45-70 · NOT_TRUSTWORTHY 0-40`.
  - fails: `max(0, 40 - 12*(fails-1) - 3*warns)`
  - warns only: `max(45, 70 - 10*warns)`
  - all pass: `100`

## 7. `GET /health` and `GET /`

- **`GET /health` → 200 `{"status":"ok"}`.** Target for platform healthchecks (Railway/Render/Fly).
- **`GET /` → 200 JSON**, human-readable and agent-discoverable: `service`, one-sentence
  `description`, the five checks with their `catches` strings, an `example_request` object,
  and an `example_curl` string (the two-number hero call). Satisfies "human-readable short
  description + example call" while being self-documenting for an agent hitting the root.

## 8. Dependencies

**Runtime (pinned, minimal):** `fastapi`, `uvicorn[standard]`, `pydantic`.
**Dev/test (pinned):** `pytest`, `httpx` (FastAPI `TestClient`), `scipy` (parity test ONLY).

**scipy is omitted from runtime — replaced by a correct pure-Python chi-square.** The one
deliberate deviation from copy-verbatim is `calibration_bias._chi2_sf`: instead of scipy +
the crude Wilson-Hilferty fallback, it computes the exact chi-square survival function
`chi2.sf(x, df) = Q(df/2, x/2)` (regularized upper incomplete gamma) in pure Python via a
series expansion for the lower branch and a Lentz continued fraction for the upper branch
(Numerical Recipes `gammq`), matching scipy to ~machine precision. This keeps runtime deps
minimal and Docker builds fast (the original rule) with **no** loss of calibration accuracy.

scipy is a **test-only** dependency: a parity test asserts the pure-Python `_chi2_sf`
matches `scipy.stats.chi2.sf` across a grid of `(x, df)` values within tolerance. Runtime
never imports scipy.

Exact version pins are finalized at build against the local Python and captured in
`requirements.txt` / `requirements-dev.txt`.

## 9. Testing

`tests/test_audit.py` with FastAPI `TestClient`:

- One PASS and one FAIL fixture per check, reusing Legibright's known-good vs known-bad
  numbers (Titanic-style leaky, bike-style honest).
- Minimal-input: `{"metrics":{"in_sample":0.99,"holdout":0.74}}` → `NOT_TRUSTWORTHY`,
  overfit FAIL, other four SKIPPED.
- Empty body `{}` → 200, all five SKIPPED, `INCONCLUSIVE`, `trust_score 50`.
- Broken blocks → 400 with the right `field`/`message` (length mismatch, lone `train_ts`,
  missing `outcomes`, non-numeric value).
- Malformed JSON / wrong type → 400 (remapped from 422).
- `GET /health` and `GET /` smoke tests.
- **Chi-square parity:** pure-Python `_chi2_sf(x, df)` vs `scipy.stats.chi2.sf(x, df)` over a
  grid (df ∈ {1..12}, x ∈ {0, 0.5, 1, 2, ... up to ~40}), asserting agreement to ≤1e-9
  absolute (with a relative check in the deep upper tail). scipy imported test-only.

## 10. Deploy

- **`Dockerfile`** (python:3.12-slim): copy, `pip install -r requirements.txt`,
  `CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`. Works on Fly/Render/Railway
  container deploys.
- **`Procfile`**: `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT` (Railway/Render buildpack).
- **`.dockerignore`**: tests, docs, `.git`, caches — small, fast image.
- Reads `$PORT` from the environment (both artifacts). `/health` is the healthcheck target.

## 11. Deliverables

- Running service (`uvicorn`) with `GET /`, `GET /health`, `POST /audit`.
- Endpoint schema (this document, section 4/6) + real local `curl` request/response
  examples verified against a running server.
- `pytest` green.
- Apache-2.0 `LICENSE`.
- Deploy-ready: Dockerfile + Procfile + .dockerignore + pinned requirements.
