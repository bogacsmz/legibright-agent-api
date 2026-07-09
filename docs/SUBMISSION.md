# NANDA Skills Registry — Submission

Copy-paste fields for the registry entry.

---

**Skill name:** Legibright Trust Audit

**One-line description:** A stateless trust/attestation service that audits a model or backtest for data leakage, overfitting, and probability miscalibration, and returns a trust verdict an agent can check before relying on the result.

**Base URL:** https://web-production-710f9.up.railway.app

**Skill document (`/skill.md`):** https://web-production-710f9.up.railway.app/skill.md

**Source (Apache-2.0):** https://github.com/bogacsmz/legibright-agent-api

**Tags:** trust, attestation, verification, ml-audit, data-leakage, calibration, guardrail

---

**What it does / why it matters for NANDA:**

Agents increasingly act on numbers other agents (or humans) hand them — a reported accuracy, a backtest ROI, a model's probabilities — with no way to tell whether those numbers are honest. Legibright is the missing trust gate: an agent POSTs whatever evidence it has (a train/test split, predictions, features, or headline metrics) and gets back a `verdict` (`TRUSTWORTHY` / `INCONCLUSIVE` / `NOT_TRUSTWORTHY`) plus a per-check breakdown, so it can refuse or downgrade a result before relying on it.

It is built for the internet-of-agents: stateless, no auth, self-documenting at `/skill.md`, and deliberately conservative — it never certifies trust on thin or absent evidence (a single passing check returns `INCONCLUSIVE`, not green), which is exactly the property an autonomous agent needs from a verifier it cannot itself second-guess.
