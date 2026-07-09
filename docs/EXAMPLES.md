# Trust Audit API — Live Examples

These request/response pairs were captured verbatim from a real running
`uvicorn app.main:app --port 8000` server (not TestClient) using `curl`.

## Health

```
$ curl -s http://localhost:8000/health; echo
{"status":"ok"}
```

## Root

```
$ curl -s http://localhost:8000/ | python -m json.tool
{
    "service": "Trust Audit API",
    "description": "POST /audit with any subset of {split, predictions, features, metrics}; each present block runs its check, absent blocks are skipped. Returns a trust_score (0-100) + verdict (TRUSTWORTHY/INCONCLUSIVE/NOT_TRUSTWORTHY).",
    "checks": [
        {
            "check": "temporal_leakage",
            "catches": "training data dated after the test cutoff — future leaks into the model",
            "input": "split.train_ts + split.test_ts"
        },
        {
            "check": "group_leakage",
            "catches": "the same entity in train and test — the model memorizes it, not the pattern",
            "input": "split.train_groups + split.test_groups"
        },
        {
            "check": "target_leakage",
            "catches": "a feature that almost perfectly predicts the label (encodes the outcome)",
            "input": "features.cols + features.outcomes"
        },
        {
            "check": "calibration_bias",
            "catches": "statistically-significant probability miscalibration a single score hides",
            "input": "predictions.predicted + predictions.outcomes"
        },
        {
            "check": "overfit_flags",
            "catches": "too-good in-sample, near-perfect memorization, holdout collapse, multiple-testing luck",
            "input": "metrics.in_sample (+holdout, n_cells_scanned)"
        }
    ],
    "example_request": {
        "metrics": {
            "in_sample": 0.99,
            "holdout": 0.74
        }
    },
    "example_curl": "curl -sX POST http://localhost:8000/audit -H 'content-type: application/json' -d '{\"metrics\":{\"in_sample\":0.99,\"holdout\":0.74}}'"
}
```

## Minimal metrics (hero: two numbers -> NOT_TRUSTWORTHY)

```
$ curl -sX POST http://localhost:8000/audit -H 'content-type: application/json' \
  -d '{"metrics":{"in_sample":0.99,"holdout":0.74}}' | python -m json.tool
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

## Leaky split

```
$ curl -sX POST http://localhost:8000/audit -H 'content-type: application/json' \
  -d '{"target":"backtest_v2","split":{"train_ts":[1,2,3],"test_ts":[2,3,4]}}' | python -m json.tool
{
    "target": "backtest_v2",
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
            "status": "FAIL",
            "headline": "TEMPORAL LEAKAGE — training data overlaps the test period",
            "detail": "2/3 (66.7%) training rows are dated at/after the earliest test row. Split is not a clean time cut (train_max=3 ≥ test_min=2); looks like a RANDOM split masquerading as walk-forward.",
            "metrics": {
                "leak_ratio": 0.6666666666666666,
                "train_max": 3.0,
                "test_min": 2.0
            },
            "reason": null
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
            "status": "SKIPPED",
            "headline": null,
            "detail": null,
            "metrics": null,
            "reason": "no `metrics` block provided"
        }
    ]
}
```

## Helpful 400

```
$ curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/audit \
  -H 'content-type: application/json' -d '{"predictions":{"predicted":[0.1,0.2],"outcomes":[1]}}'
400
```
