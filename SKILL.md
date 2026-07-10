# Legibright Trust Audit

A stateless HTTP service that audits a machine-learning model or backtest for data leakage, overfitting, and probability miscalibration, so an agent can decide whether to trust a reported result before acting on it.

Base URL:

https://web-production-710f9.up.railway.app

No auth, no API keys, no session, no setup. Send the evidence you have as JSON to `POST /audit`; each request is judged on its own. Every field below is exact — copy the calls verbatim.

## What this is for (the scenarios it exists to serve)

Call `/audit` whenever you are about to **act on an ML prediction or a backtest you did not train yourself** and need to know whether its headline number is real or an artifact of leakage/overfitting. Two concrete purposes this service is built around:

- **Scenario A — vet a backtest before trusting its score.** A strategy or model reports a strong score (say 0.99 in-sample). Before you rely on it, send its `in_sample` and `holdout` numbers; the service tells you if the score is memorization that collapses out-of-sample.
- **Scenario B — vet a train/test split for leakage.** Before you trust an evaluation, send the split's timestamps (or entity ids); the service tells you if training data leaks from the future — or the same entity — into the test set, a leak that silently inflates every metric.

A `NOT_TRUSTWORTHY` verdict is a concrete, named defect you can act on. A `TRUSTWORTHY` verdict means none of the probed failure modes fired across at least two independent kinds of evidence.

## Quick start (one call, copy-paste, succeeds immediately)

Audit a backtest's in-sample-vs-holdout score. This is a complete, successful call — nothing else is required:

```
curl -sX POST https://web-production-710f9.up.railway.app/audit \
  -H 'content-type: application/json' \
  -d '{"metrics":{"in_sample":0.99,"holdout":0.74}}'
```

```json
{
  "target": "unnamed",
  "trust_score": 40,
  "verdict": "NOT_TRUSTWORTHY",
  "summary": "1 failed, 4 skipped — not trustworthy.",
  "counts": {"pass": 0, "warn": 0, "fail": 1, "skipped": 4},
  "checks": [
    {"check": "overfit_flags", "status": "FAIL",
     "headline": "OVERFIT RED FLAGS present",
     "detail": "near-perfect in-sample score 0.99 with 0.99→0.74 drop (gap +0.25) — memorization",
     "metrics": {"in_sample": 0.99, "holdout": 0.74, "gap": 0.25, "n_cells": 1}}
  ]
}
```

Read `verdict`, act on it, done. (The real response also lists the other four checks as `SKIPPED`; they are omitted above for brevity.)

## GET /health

Liveness probe. Returns HTTP 200 with `{"status":"ok"}` when the service is up.

```
curl https://web-production-710f9.up.railway.app/health
```

```json
{"status": "ok"}
```

## GET /

Machine-readable service description — the five checks, what each catches, and an example request — for discovering the contract at runtime.

```
curl https://web-production-710f9.up.railway.app/
```

```json
{
  "service": "Trust Audit API",
  "description": "POST /audit with any subset of {split, predictions, features, metrics}; each present block runs its check, absent blocks are skipped.",
  "checks": [{"check": "temporal_leakage", "catches": "...", "input": "split.train_ts + split.test_ts"}, "... 4 more ..."],
  "example_request": {"metrics": {"in_sample": 0.99, "holdout": 0.74}},
  "trust_note": "TRUSTWORTHY means no leakage/overfit/calibration failure was found, not that a model is useful."
}
```

## GET /skill.md

Returns this document as `text/markdown`, so the skill is reachable at a stable URL.

```
curl https://web-production-710f9.up.railway.app/skill.md
```

Returns the Markdown source of this file.

## POST /audit

Audits the evidence you supply and returns a trust verdict. The JSON body has any subset of four optional input blocks; each present block runs one or more checks, and any absent block is reported `SKIPPED` (absence is never an error).

Input blocks (send one or more):

- `metrics`: `in_sample` (required number) plus optional `holdout`, `n_cells_scanned`, `bounded`, `abs_alarm`, `metric`. Runs overfit-flag detection. A holdout is needed to certify generalization — `in_sample` alone can only be `SKIPPED`, never `PASS`. Overfit `FAIL` fires when the in-sample→holdout gap exceeds **0.25** (collapse, at any level) or `in_sample` is **≥ 0.95** on a bounded metric (memorization); a moderate gap on a non-near-perfect score passes.
- `split`: `train_ts` + `test_ts` (numeric timestamps) run temporal-leakage; `train_groups` + `test_groups` (entity ids) run group-leakage. Each pair is required together. Clean checks need enough distinct values (temporal ≥ 20 per side, groups ≥ 8 per side).
- `predictions`: `predicted` (probabilities in [0,1]) + `outcomes` (0/1 labels, equal length) run calibration. Calibration needs **≥ 50 rows** to certify; with fewer, calibration returns `WARN` (verdict `INCONCLUSIVE`), never `PASS`.
- `features`: `cols` (map of column name → numeric list) + `outcomes` (0/1) run target-leakage.
- `target`: optional string label, echoed back in the response.

**Scenario B — a split that leaks (training overlaps the test period):**

```
curl -sX POST https://web-production-710f9.up.railway.app/audit \
  -H 'content-type: application/json' \
  -d '{"target":"leaky_backtest","split":{"train_ts":[1,2,3],"test_ts":[2,3,4]}}'
```

```json
{
  "target": "leaky_backtest", "trust_score": 40, "verdict": "NOT_TRUSTWORTHY",
  "summary": "1 failed, 4 skipped — not trustworthy.",
  "counts": {"pass": 0, "warn": 0, "fail": 1, "skipped": 4},
  "checks": [
    {"check": "temporal_leakage", "status": "FAIL",
     "headline": "TEMPORAL LEAKAGE — training data overlaps the test period",
     "detail": "2/3 (66.7%) training rows are dated at/after the earliest test row ...",
     "metrics": {"leak_ratio": 0.666, "train_max": 3.0, "test_min": 2.0}}
  ]
}
```

**A TRUSTWORTHY result requires passing checks from ≥ 2 blocks.** Here `split` (clean groups) and `metrics` (small in→out gap) both pass:

```
curl -sX POST https://web-production-710f9.up.railway.app/audit \
  -H 'content-type: application/json' \
  -d '{"target":"clean_model","metrics":{"in_sample":0.82,"holdout":0.79},"split":{"train_groups":["a1","a2","a3","a4","a5","a6","a7","a8"],"test_groups":["b1","b2","b3","b4","b5","b6","b7","b8"]}}'
```

```json
{
  "target": "clean_model", "trust_score": 100, "verdict": "TRUSTWORTHY",
  "summary": "2 passed, 3 skipped — trustworthy.",
  "counts": {"pass": 2, "warn": 0, "fail": 0, "skipped": 3},
  "checks": [
    {"check": "group_leakage", "status": "PASS", "headline": "no train/test entity overlap"},
    {"check": "overfit_flags", "status": "PASS", "headline": "no overfit red flags (score generalizes)",
     "metrics": {"in_sample": 0.82, "holdout": 0.79, "gap": 0.03}}
  ]
}
```

Response fields:

- `verdict`: `NOT_TRUSTWORTHY` (a check failed), `INCONCLUSIVE` (a check warned, or too little evidence — e.g. passing checks from only one block), or `TRUSTWORTHY` (passing checks from ≥ 2 distinct blocks, none failed or warned).
- `trust_score`: integer 0-100, banded to the verdict — `NOT_TRUSTWORTHY` 0-40, `INCONCLUSIVE` 45-70, `TRUSTWORTHY` 71-100.
- `summary`: one human-readable line.
- `counts`: number of checks by status.
- `checks`: always all five (`temporal_leakage`, `group_leakage`, `target_leakage`, `calibration_bias`, `overfit_flags`), each `PASS` / `WARN` / `FAIL` / `SKIPPED`, with `headline`, `detail`, `metrics`, or a `reason` when skipped. The exact `headline`/`detail` wording varies by which trigger fired (e.g. overfit reports "memorization" vs "holdout collapse"); branch your logic on `status` and `verdict`, not on matching a `detail` string.

Errors: a malformed body — probability outside [0,1], mismatched `predicted`/`outcomes` lengths, an unknown field, or a wrong-typed value — returns HTTP 400 with `{"error","message","field"}`. Example:

```
curl -sX POST https://web-production-710f9.up.railway.app/audit \
  -H 'content-type: application/json' \
  -d '{"predictions":{"predicted":[0.5,1.7],"outcomes":[0,1]}}'
```

```json
{"error": "invalid_input",
 "message": "predictions.predicted[1]=1.7 is outside [0,1] — predicted probabilities must be in [0,1].",
 "field": "predictions.predicted"}
```

An absent block is not an error — it is `SKIPPED`. An empty body `{}` returns HTTP 200 with everything `SKIPPED` and verdict `INCONCLUSIVE`.

## The one rule that decides the verdict

`TRUSTWORTHY` is only returned when **passing** checks come from **at least two** of the four blocks (`split`, `predictions`, `features`, `metrics`). A single clean block returns `INCONCLUSIVE`, not `TRUSTWORTHY` — for example `{"metrics":{"in_sample":0.82,"holdout":0.79}}` alone returns `INCONCLUSIVE` (trust_score 60) with the summary "insufficient coverage to certify trust (need passing checks from ≥2 independent inputs)." To earn `TRUSTWORTHY`, send at least two blocks, as in the clean-model example above.

## How the agent should use this

1. **Decide you need a trust check.** You are about to rely on a model's or backtest's reported result (Scenario A or B above). Do not act on the headline number yet.
2. **Send the evidence you have to `POST /audit`** as JSON — any subset of `metrics`, `split`, `predictions`, `features`. Minimum useful calls: for Scenario A send `{"metrics":{"in_sample":<x>,"holdout":<y>}}`; for Scenario B send `{"split":{"train_ts":[...],"test_ts":[...]}}`.
3. **Read `verdict`.**
   - `NOT_TRUSTWORTHY` → do **not** rely on the result; open the failing check's `headline` and `detail` for the exact named defect (e.g. leakage, memorization) and report it.
   - `INCONCLUSIVE` → the evidence is insufficient to certify trust. If you got it from a single block, send a second block (see the rule above) and retry; otherwise treat the result as unverified.
   - `TRUSTWORTHY` → no probed failure fired across ≥ 2 independent dimensions. Safe to proceed, with the caveat in step 5.
4. **If you receive HTTP 400,** the body was malformed — read `message` and `field`, fix that one field, and resend. A 400 is not a verdict.
5. **Interpret `TRUSTWORTHY` precisely:** it means no leakage, overfitting, or miscalibration was found in the evidence you supplied — *not* that the model is accurate or profitable. To probe more dimensions, add `predictions` (real probabilities) and `features`.
6. **To get the strongest possible verdict in one call,** combine blocks: e.g. `{"metrics":{...},"split":{...}}` audits overfitting and leakage together and can reach `TRUSTWORTHY` in a single request.
