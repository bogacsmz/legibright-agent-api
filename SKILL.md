# Legibright Trust Audit

A stateless HTTP trust/attestation service that audits a model or backtest for data leakage, overfitting, and probability miscalibration, and returns a trust verdict an agent can check before relying on the result.

Base URL:

https://web-production-710f9.up.railway.app

The service is stateless: no auth, no keys, no session. Send the evidence you have; each request is judged on its own.

## GET /health

Liveness probe. Returns 200 when the service is up.

```
curl https://web-production-710f9.up.railway.app/health
```

```json
{"status": "ok"}
```

## GET /

Machine-readable service description: the five checks, what each catches, and an example request. Use it to discover the contract at runtime.

```
curl https://web-production-710f9.up.railway.app/
```

```json
{
  "service": "Trust Audit API",
  "description": "POST /audit with any subset of {split, predictions, features, metrics}; each present block runs its check, absent blocks are skipped. Returns a trust_score (0-100) + verdict (TRUSTWORTHY/INCONCLUSIVE/NOT_TRUSTWORTHY).",
  "checks": [ { "check": "temporal_leakage", "catches": "...", "input": "split.train_ts + split.test_ts" }, "... 4 more ..." ],
  "example_request": { "metrics": { "in_sample": 0.99, "holdout": 0.74 } },
  "example_curl": "curl -sX POST .../audit -H 'content-type: application/json' -d '{\"metrics\":{\"in_sample\":0.99,\"holdout\":0.74}}'",
  "trust_note": "verdict requires no probed failure across >=2 independent input blocks; TRUSTWORTHY means no leakage/overfit/calibration failure was found, not that a model is useful."
}
```

## GET /skill.md

Returns this document as text/markdown. Present so the skill is reachable at a stable URL.

```
curl https://web-production-710f9.up.railway.app/skill.md
```

Returns the Markdown source of this file.

## POST /audit

Audits the evidence you supply and returns a trust verdict. The request body is JSON with any subset of four optional blocks; each present block runs one check, absent blocks are reported `SKIPPED`.

Input blocks:

- `split`: `train_ts` + `test_ts` (numeric timestamps) run temporal-leakage; `train_groups` + `test_groups` run group-leakage. Paired fields are required together.
- `predictions`: `predicted` (probabilities in [0,1]) + `outcomes` (0/1 labels, equal length) run calibration.
- `features`: `cols` (map of column name to numeric list) + `outcomes` (0/1) run target-leakage.
- `metrics`: `in_sample` (required) + optional `holdout`, `n_cells_scanned`, `bounded`, `abs_alarm`, `metric` run overfit-flag detection.
- `target`: optional label echoed back.

Example (a split that leaks — training overlaps the test period):

```
curl -sX POST https://web-production-710f9.up.railway.app/audit \
  -H 'content-type: application/json' \
  -d '{"target":"leaky_backtest","split":{"train_ts":[1,2,3],"test_ts":[2,3,4]}}'
```

```json
{
  "target": "leaky_backtest",
  "trust_score": 40,
  "verdict": "NOT_TRUSTWORTHY",
  "summary": "1 failed, 4 skipped — not trustworthy.",
  "counts": { "pass": 0, "warn": 0, "fail": 1, "skipped": 4 },
  "checks": [
    { "check": "temporal_leakage", "status": "FAIL",
      "headline": "TEMPORAL LEAKAGE — training data overlaps the test period",
      "detail": "2/3 (66.7%) training rows are dated at/after the earliest test row ...",
      "metrics": { "leak_ratio": 0.666, "train_max": 3.0, "test_min": 2.0 } }
  ]
}
```

Response fields:

- `verdict`: `NOT_TRUSTWORTHY` (a check failed), `INCONCLUSIVE` (a check warned, or too little evidence), or `TRUSTWORTHY` (passing findings from >=2 distinct input blocks, none failed or warned).
- `trust_score`: integer 0-100, banded to the verdict — `NOT_TRUSTWORTHY` 0-40, `INCONCLUSIVE` 45-70, `TRUSTWORTHY` 71-100.
- `summary`: one human-readable line.
- `counts`: number of checks by status.
- `checks`: always all five, each `PASS` / `WARN` / `FAIL` / `SKIPPED` with `headline`, `detail`, `metrics`, or a `reason` when skipped.

Errors: malformed, non-finite (`NaN`/`Infinity`), out-of-range, wrong-type, or oversized input returns HTTP 400 with `{"error","message","field"}`. An absent block is not an error — it is `SKIPPED`.

## How the agent should use this

1. Before you rely on a model's or backtest's reported results, POST whatever evidence you have (`split`, `predictions`, `features`, `metrics`) to `/audit`.
2. Read `verdict`. `NOT_TRUSTWORTHY` — do not rely on the result; a real failure was detected (see the failing check's `headline`/`detail`). `INCONCLUSIVE` — the evidence is insufficient to certify trust; gather and submit more before relying. `TRUSTWORTHY` — no probed failure mode fired across at least two independent dimensions.
3. Inspect `checks[]` to see which checks ran (`PASS`/`WARN`/`FAIL`) and which were `SKIPPED` and why (`reason`). A verdict backed by more passing blocks is stronger.
4. If you receive HTTP 400, correct the input per `message` and `field`, then retry. Do not treat a 400 as a verdict.
5. Interpret `TRUSTWORTHY` precisely: it means no leakage, overfitting, or miscalibration was found in the evidence supplied — not that the model is useful or accurate. For a usefulness signal, supply `features` and real varied `predictions`.
