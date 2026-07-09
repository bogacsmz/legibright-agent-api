# Trust Audit API

Stateless statistical-honesty auditor for ML models and backtests: leakage, overfit, and calibration checks over any subset of `{split, predictions, features, metrics}`, returned as a single `trust_score` (0-100) + `verdict`.

## Quickstart

```bash
curl -sX POST http://localhost:8000/audit -H 'content-type: application/json' \
  -d '{"metrics":{"in_sample":0.99,"holdout":0.74}}'
```

Response (captured verbatim from a running server — see `docs/EXAMPLES.md`):

```json
{
    "target": "unnamed",
    "trust_score": 40,
    "verdict": "NOT_TRUSTWORTHY",
    "summary": "1 failed, 4 skipped — not trustworthy.",
    "counts": {
        "pass": 0,
        "warn": 0,
        "fail": 1,
        "skipped": 4
    },
    "checks": [
        {
            "check": "temporal_leakage",
            "status": "SKIPPED",
            "headline": null,
            "detail": null,
            "metrics": null,
            "reason": "no `split.train_ts`/`split.test_ts` provided"
        },
        {
            "check": "group_leakage",
            "status": "SKIPPED",
            "headline": null,
            "detail": null,
            "metrics": null,
            "reason": "no `split.train_groups`/`split.test_groups` provided"
        },
        {
            "check": "target_leakage",
            "status": "SKIPPED",
            "headline": null,
            "detail": null,
            "metrics": null,
            "reason": "no `features` block provided"
        },
        {
            "check": "calibration_bias",
            "status": "SKIPPED",
            "headline": null,
            "detail": null,
            "metrics": null,
            "reason": "no `predictions` block provided"
        },
        {
            "check": "overfit_flags",
            "status": "FAIL",
            "headline": "OVERFIT RED FLAGS present",
            "detail": "near-perfect in-sample score 0.99 with 0.99→0.74 drop (gap +0.25) — memorization",
            "metrics": {
                "in_sample": 0.99,
                "holdout": 0.74,
                "gap": 0.25,
                "n_cells": 1
            },
            "reason": null
        }
    ]
}
```

Two numbers (`in_sample`, `holdout`) are enough to catch overfitting — the other four checks report `SKIPPED` because their input blocks weren't given, not because anything is wrong.

## What TRUSTWORTHY means (and doesn't)

`TRUSTWORTHY` means: no probed failure mode (leakage, overfit gap, calibration bias) fired across **≥2 independent input blocks**. It does **not** mean the model is useful, accurate, or discriminating — a constant predictor at the base rate is genuinely calibrated and can contribute a clean check. Callers wanting a usefulness/discrimination guarantee should supply real, varied `predictions` and a `features` block for target-leakage coverage, and read the check `detail` strings, not just the verdict. Full scope, adversarial-audit findings, and honest limits: [`docs/VERIFICATION.md`](docs/VERIFICATION.md).

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Endpoints

- `POST /audit` — run the audit against any subset of `{split, predictions, features, metrics}`; returns a scored, per-check report.
- `GET /health` — liveness probe; returns `{"status": "ok"}`.
- `GET /` — self-documenting: service description, the five checks, a ready-to-run example curl, and a `trust_note` on what `TRUSTWORTHY` does/doesn't certify.

## Request schema

`AuditRequest` accepts an optional `target` (string label, default `"unnamed"`) plus any subset of four blocks. Each present block runs its check; each absent block is `SKIPPED`. Extra/unknown fields are rejected (`extra="forbid"`).

| Block | Fields | Check it feeds |
|---|---|---|
| `split` | `train_ts`, `test_ts` (paired) · `train_groups`, `test_groups` (paired) · `entity` (str, default `"entity"`) | `temporal_leakage` (needs `train_ts`+`test_ts`) and `group_leakage` (needs `train_groups`+`test_groups`) |
| `predictions` | `predicted: list[float]`, `outcomes: list[int]` (equal length) | `calibration_bias` |
| `features` | `cols: dict[str, list[float]]`, `outcomes: list[int]` (every column equal length to outcomes) | `target_leakage` |
| `metrics` | `in_sample: float` (required) · `holdout: float` (optional) · `n_cells_scanned: int` (default `1`) · `bounded: bool` (default `true`) · `abs_alarm: float` (optional) · `metric: str` (default `"score"`) | `overfit_flags` |

## Response schema

`AuditResponse`:

- `target` — echoed request label.
- `trust_score` — integer 0-100.
- `verdict` — one of `TRUSTWORTHY` (score 71-100) / `INCONCLUSIVE` (score 45-70) / `NOT_TRUSTWORTHY` (score 0-40), subject to the coverage rule below.
- `summary` — one-line human-readable rollup, e.g. `"1 failed, 4 skipped — not trustworthy."`.
- `counts` — `{pass, warn, fail, skipped}` tallies across the five checks.
- `checks` — list of exactly five `CheckResult` objects, **always** — every check (`temporal_leakage`, `group_leakage`, `target_leakage`, `calibration_bias`, `overfit_flags`) always appears in the response, whether it ran or was skipped. Each has:
  - `status` — `PASS` / `WARN` / `FAIL` / `SKIPPED`.
  - `headline`, `detail`, `metrics` — populated when the check ran (`null` when `SKIPPED`).
  - `reason` — populated when `SKIPPED` explaining which input block was missing (`null` otherwise).

### Verdict / coverage rule

`verdict` is not a raw score threshold — it's gated by evidence coverage:

1. Any `FAIL` → `NOT_TRUSTWORTHY`, decisive regardless of coverage.
2. Else any `WARN` → `INCONCLUSIVE`.
3. Else `TRUSTWORTHY` requires passing findings from **≥2 distinct input blocks** (`split` / `predictions` / `features` / `metrics`) — otherwise `INCONCLUSIVE`. A single clean check, or two `PASS`es both coming from the one `split` block (temporal + group), is `INCONCLUSIVE`, not green.
4. Zero checks ran (empty body) → `INCONCLUSIVE` at score 50.

This exists so the service can never be tricked into certifying trust on no — or thin — real evidence; see the "fake-green" table in [`docs/VERIFICATION.md`](docs/VERIFICATION.md).

Each check also has a data floor below which it reports `SKIPPED` instead of certifying on too little data: `target_leakage` needs ≥30 rows in both classes, `calibration_bias` needs ≥50 rows, `temporal_leakage` needs ≥20 distinct timestamps per side, `group_leakage` needs ≥8 distinct entities per side.

## What each check catches

| Check | Catches | Input |
|---|---|---|
| `temporal_leakage` | training data dated after the test cutoff — future leaks into the model | `split.train_ts` + `split.test_ts` |
| `group_leakage` | the same entity in train and test — the model memorizes it, not the pattern | `split.train_groups` + `split.test_groups` |
| `target_leakage` | a feature that almost perfectly predicts the label (encodes the outcome) | `features.cols` + `features.outcomes` |
| `calibration_bias` | statistically-significant probability miscalibration a single score hides | `predictions.predicted` + `predictions.outcomes` |
| `overfit_flags` | too-good in-sample, near-perfect memorization, holdout collapse, multiple-testing luck | `metrics.in_sample` (+`holdout`, `n_cells_scanned`) |

## Errors

Invalid input (a *present* block that's malformed, mismatched lengths, wrong types, out-of-range values, oversized, or an unknown field) returns HTTP 400 with a consistent envelope:

```json
{"error": "invalid_input", "message": "<human-readable reason>", "field": "<dotted path or null>"}
```

400 is returned for:

- **Non-finite floats** — `NaN` / `Infinity` / `-Infinity` anywhere a float is expected.
- **Out-of-range values** — `predictions.predicted` outside `[0, 1]`; `outcomes` values not in `{0, 1}`.
- **Wrong type** — a bool where a `metrics` number is expected (e.g. `true` for `in_sample`).
- **Mismatched lengths** — e.g. `predictions.predicted` and `predictions.outcomes` different length, or a `features.cols` column length not matching `outcomes`.
- **Oversized input (DoS guard)** — any array > 100,000 elements, > 1,000 feature columns, or > 2,000,000 feature cells.
- **Malformed JSON / wrong shape / unknown field** — invalid JSON body, wrong field type, or an unrecognized field (Pydantic's 422 is remapped to this same 400 envelope).

An **absent** block is not an error — it's `SKIPPED` (200). A completely empty body (`{}`) is 200 with all five checks `SKIPPED` and verdict `INCONCLUSIVE`.

Example — mismatched `predictions` lengths:

```
$ curl -sX POST http://localhost:8000/audit -H 'content-type: application/json' \
  -d '{"predictions":{"predicted":[0.1,0.2],"outcomes":[1]}}'
{
    "error": "invalid_input",
    "message": "predictions.predicted has 2 items but predictions.outcomes has 1 — they must be equal length.",
    "field": "predictions.outcomes"
}
```

Example — non-finite float rejected:

```
$ curl -sX POST http://localhost:8000/audit -H 'content-type: application/json' \
  -d '{"metrics":{"in_sample":NaN}}'
{
    "error": "invalid_input",
    "message": "metrics.in_sample is non-finite (NaN/Infinity) — must be a finite number.",
    "field": "metrics.in_sample"
}
```

Unexpected server errors return HTTP 500 with the same envelope shape (`{"error": "internal_error", "message": "...", "field": null}`) and never leak internal details.

## Deploy

**Docker:**

```bash
docker build -t trust-audit-api .
docker run -d -p 8010:8000 --name ta trust-audit-api
curl -s http://localhost:8010/health
```

**Procfile** (Railway, Render, Heroku-style platforms — reads `$PORT` from the environment):

```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

The container/process listens on `$PORT` (defaults to `8000` if unset) and exposes `GET /health` for platform healthchecks.

## License

Apache-2.0 — see `LICENSE`.
