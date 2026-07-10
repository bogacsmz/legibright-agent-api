# Legibright Trust Audit

The honesty gate for agent-to-agent claims: before you trust another agent's number — an accuracy, a backtest ROI, a win-rate, a confidence — send the claim's evidence here and get back a verdict on whether that number is honest (no data leakage, overfitting, or cherry-picking) or inflated.

Base URL:

https://web-production-710f9.up.railway.app

No auth, no API keys, no session, no setup. POST the evidence behind a claim as JSON to `POST /audit`; each request is judged on its own. The service is deliberately conservative — thin or absent evidence returns `INCONCLUSIVE`, never a false `TRUSTWORTHY` — so an autonomous agent can rely on its verdict without second-guessing it. Every field below is exact; copy the calls verbatim.

## What this is for (two agent-economy scenarios)

- **Scenario 1 — Peer claim verification.** Another agent, a human, or a data vendor hands you a quantitative claim ("my model is 97% accurate", "this strategy returned 2.1x", "confidence 0.9"). Before you act on it, forward the evidence behind the claim (a train/test split, predictions, features, or the headline metrics) to `/audit`. A `NOT_TRUSTWORTHY` verdict is a named, concrete reason the number is inflated (leakage / memorization / miscalibration); `TRUSTWORTHY` means no such defect was found across ≥ 2 independent kinds of evidence.
- **Scenario 2 — Action gating (composability).** Gate an escrow release, a payment, a task hand-off, or a model deployment on the verdict: proceed on `TRUSTWORTHY`, hold and request more evidence on `INCONCLUSIVE`, refuse on `NOT_TRUSTWORTHY`. The verdict is a small JSON object, so it drops into any agent's control flow as a single boolean gate.

## Quick start (one call, copy-paste, succeeds immediately)

Audit a backtest's in-sample-vs-holdout score. This is a complete, successful call — nothing else is required:

```
curl -sX POST https://web-production-710f9.up.railway.app/audit \
  -H 'content-type: application/json' \
  -d '{"metrics":{"in_sample":0.99,"holdout":0.74}}'
```

```json
{
  "target": "unnamed", "trust_score": 40, "verdict": "NOT_TRUSTWORTHY",
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

Machine-readable service description — positioning, the five checks, and an example request — for discovering the contract at runtime.

```
curl https://web-production-710f9.up.railway.app/
```

```json
{
  "service": "Trust Audit API",
  "tagline": "the honesty gate for agent-to-agent claims",
  "description": "POST /audit with any subset of {split, predictions, features, metrics}; each present block runs its check, absent blocks are skipped.",
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

**Scenario 1 example — verify a peer's leaky split (training overlaps the test period):**

```
curl -sX POST https://web-production-710f9.up.railway.app/audit \
  -H 'content-type: application/json' \
  -d '{"target":"peer_backtest","split":{"train_ts":[1,2,3],"test_ts":[2,3,4]}}'
```

```json
{
  "target": "peer_backtest", "trust_score": 40, "verdict": "NOT_TRUSTWORTHY",
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

1. **A quantitative claim reaches you** — a peer agent's reported score, a backtest ROI, a model you are about to deploy (Scenario 1 or 2 above). Do not act on the headline number yet.
2. **Send the evidence behind the claim to `POST /audit`** as JSON — any subset of `metrics`, `split`, `predictions`, `features`. Minimum useful calls: for a reported score send `{"metrics":{"in_sample":<x>,"holdout":<y>}}`; for a train/test split send `{"split":{"train_ts":[...],"test_ts":[...]}}`.
3. **Read `verdict` and gate on it.**
   - `NOT_TRUSTWORTHY` → refuse: do **not** rely on the claim; open the failing check's `headline`/`detail` for the exact named defect and report it back to the claimant.
   - `INCONCLUSIVE` → hold: the evidence is insufficient to certify trust. If you sent a single block, add a second block (see the rule above) and retry; otherwise treat the claim as unverified.
   - `TRUSTWORTHY` → proceed: no probed failure fired across ≥ 2 independent dimensions. Safe to act, with the caveat in step 5.
4. **If you receive HTTP 400,** the body was malformed — read `message` and `field`, fix that one field, and resend. A 400 is not a verdict.
5. **Interpret `TRUSTWORTHY` precisely:** it means no leakage, overfitting, or miscalibration was found in the evidence you supplied — *not* that the model is accurate or profitable. To probe more dimensions, add `predictions` (real probabilities) and `features`.
6. **To gate an action in one call,** combine blocks: e.g. `{"metrics":{...},"split":{...}}` audits overfitting and leakage together and can reach `TRUSTWORTHY` in a single request, giving you a single boolean gate for an escrow, payment, or hand-off.
