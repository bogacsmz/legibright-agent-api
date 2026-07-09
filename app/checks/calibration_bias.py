"""Auditor check: calibration / miscalibration — sample-size aware.

A single ROI/accuracy number hides whether the model's *probabilities* are honest. But a
naive fixed ECE threshold is itself dishonest: empirical ECE is positively biased at small n,
so a fixed cutoff cries wolf on perfectly-calibrated models when the holdout is small.

So we use the **Hosmer-Lemeshow goodness-of-fit test** (chi-square p-value over quantile bins),
which accounts for n, and only flag when the deviation is BOTH statistically significant AND
materially large (ECE). Quantile bins (not equal-width) avoid the within-bin cancellation that
lets 0.45-for-0 / 0.55-for-1 look "calibrated". Under ~50 rows we do NOT certify — we WARN.

Distilled from betting pipelines where multiplicative de-vig inflated longshots.
"""
from __future__ import annotations

import math
from typing import Sequence

from .base import Check, Finding, Severity

_MIN_N = 50


class CalibrationBiasCheck(Check):
    id = "calibration_bias"

    def run(
        self,
        predicted: Sequence[float],
        outcomes: Sequence[int],
        *,
        n_bins: int = 10,
        p_fail: float = 0.01,
        p_warn: float = 0.05,
        ece_material: float = 0.03,
    ) -> Finding:
        n = len(predicted)
        if n != len(outcomes):
            # a misaligned caller must NOT get a green calibration pass
            return Finding(self.id, Severity.WARN,
                           f"calibration NOT assessed — {n} predictions vs {len(outcomes)} outcomes",
                           suggested_tags=["audit-warn"])
        if n < _MIN_N:
            # honest: too few rows to certify calibration either way (do NOT stamp OK)
            return Finding(self.id, Severity.WARN,
                           f"calibration NOT certified — only {n} rows (< {_MIN_N})",
                           suggested_tags=["audit-warn"])

        bins = _quantile_bins(list(zip(predicted, outcomes)), n_bins)
        hl, p, ece, rows, used = _hosmer_lemeshow(bins, n)
        detail = f"HL χ²={hl:.1f}, p={p:.3g}, ECE={ece:.3f} over {len(bins)} bins"

        if used < len(bins):
            # HL is COMPROMISED: one or more bins are degenerate (hard 0/1 predictions → E∈{0,ng},
            # denom=0) and were dropped from χ². The resulting p understates miscalibration because
            # the badly-calibrated hard bins didn't count — yet they DO count toward ECE. So a model
            # that is soft-and-honest on some rows but confidently-wrong 0/1 on others would reach a
            # high p and slip through the OK branch. Fall back to the observed ECE: any dropped bin +
            # material ECE ⇒ NOT certifiable (never OK). Immaterial ECE (the dropped bins were
            # actually correct, contributing ~0 error) still passes.
            if ece >= ece_material:
                return Finding(self.id, Severity.WARN,
                               f"calibration NOT certifiable — HL compromised "
                               f"({len(bins) - used}/{len(bins)} bins non-probabilistic), "
                               f"observed ECE {ece:.3f} ≥ {ece_material}",
                               detail=detail,
                               metrics={"hl": hl, "p": p, "ece": ece, "hl_bins_used": used},
                               suggested_tags=["audit-warn"])
            return Finding(self.id, Severity.OK,
                           f"well calibrated — ECE {ece:.3f} immaterial "
                           f"({len(bins) - used}/{len(bins)} bins degenerate but low-error)",
                           detail=detail, metrics={"hl": hl, "p": p, "ece": ece, "hl_bins_used": used})

        if p < p_fail and ece >= ece_material:
            return Finding(self.id, Severity.FAIL,
                           f"CALIBRATION OFF (significant, p={p:.2g}, ECE={ece:.3f})",
                           detail=detail + " | " + "; ".join(rows),
                           metrics={"hl": hl, "p": p, "ece": ece},
                           suggested_tags=["audit-failed"])
        if p < p_warn and ece >= ece_material:
            return Finding(self.id, Severity.WARN, f"calibration suspect (p={p:.2g}, ECE={ece:.3f})",
                           detail=detail, metrics={"hl": hl, "p": p, "ece": ece},
                           suggested_tags=["audit-warn"])
        # OK — either not significant, or significant but IMMATERIAL (common at large n).
        # Lead the headline with ECE (the metric that justifies the verdict); contextualize the
        # bare p instead of letting a tiny "significant" p look like it contradicts the pass.
        if p < p_warn:
            msg = (f"well calibrated — ECE {ece:.3f} below the {ece_material} material floor "
                   f"(HL deviation significant, p={p:.2g}, but immaterial at n={n})")
        else:
            msg = f"well calibrated — ECE {ece:.3f}, no significant HL deviation (p={p:.2g})"
        return Finding(self.id, Severity.OK, msg, detail=detail,
                       metrics={"hl": hl, "p": p, "ece": ece})


def _quantile_bins(pairs, n_bins):
    """Split rows into ~equal-count bins by predicted prob (stable, no empty bins)."""
    pairs = sorted(pairs, key=lambda x: x[0])
    n = len(pairs)
    k = max(2, min(n_bins, n // 5))     # keep >=5 rows/bin so HL is meaningful
    bins = []
    for b in range(k):
        lo, hi = b * n // k, (b + 1) * n // k
        chunk = pairs[lo:hi]
        if chunk:
            bins.append(chunk)
    return bins


def _hosmer_lemeshow(bins, n):
    hl = 0.0
    ece = 0.0
    rows = []
    used = 0                       # bins that actually contributed to χ² (denom>0)
    for b, chunk in enumerate(bins):
        ng = len(chunk)
        pred = sum(p for p, _ in chunk) / ng
        obs = sum(y for _, y in chunk) / ng
        E = sum(p for p, _ in chunk)
        O = sum(y for _, y in chunk)
        ece += (ng / n) * abs(pred - obs)
        denom = E * (1 - E / ng) if 0 < E < ng else 0.0
        if denom > 0:
            hl += (O - E) ** 2 / denom
            used += 1
        rows.append(f"[b{b}] pred={pred:.2f} obs={obs:.2f} n={ng}")
    df = max(len(bins) - 2, 1)
    p = _chi2_sf(hl, df)
    return hl, p, ece, rows, used


def _chi2_sf(x, df):
    """Exact chi-square upper-tail survival function, pure Python.

    chi2.sf(x, df) == Q(df/2, x/2), the regularized upper incomplete gamma.
    Matches the reference chi2 survival function to ~machine precision.
    Pure Python, no third-party stats library at runtime.
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
