"""Auditor check: target leakage — a feature that (almost) encodes the label.

The split can be perfectly temporal and the model still be a fraud if a FEATURE leaks the
target (e.g. a column derived from the outcome, or an id that target-encodes it). Then both
in-sample AND holdout look great, so the split/overfit checks stay silent. This check looks at
the feature matrix directly: any single feature that alone separates the label almost perfectly
(rank-AUC ≥ alarm) is a leak. Pure numpy — no sklearn dependency in the core.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from .base import Check, Finding, Severity


class TargetLeakageCheck(Check):
    id = "target_leakage"

    def run(
        self,
        features: Mapping[str, Sequence[float]],
        outcomes: Sequence[int],
        *,
        auc_alarm: float = 0.99,
    ) -> Finding:
        y = list(outcomes)
        pos = sum(1 for v in y if v == 1)
        if len(y) < 30 or pos == 0 or pos == len(y):
            return Finding(self.id, Severity.OK, "target leakage: not enough label variation to test")

        leaks = []
        for name, vals in features.items():
            auc = _rank_auc(list(vals), y)
            if auc is None:
                continue
            auc = max(auc, 1 - auc)         # direction-agnostic
            if auc >= auc_alarm:
                leaks.append(f"{name} (AUC={auc:.3f})")

        if leaks:
            return Finding(
                self.id, Severity.FAIL,
                "TARGET LEAKAGE — a feature almost perfectly predicts the label",
                detail="near-perfect single-feature separation: " + ", ".join(leaks) +
                       ". A feature likely encodes the outcome; the model isn't predicting, it's peeking.",
                metrics={"leaky_features": len(leaks)},
                suggested_tags=["audit-failed", "target-leakage"], suggested_incident=True,
            )
        return Finding(self.id, Severity.OK, "no single-feature target leakage detected")


def _rank_auc(x: list[float], y: list[int]) -> float | None:
    """AUC of feature x as a score for label y, via the Mann-Whitney U rank statistic."""
    pairs = [(xi, yi) for xi, yi in zip(x, y) if isinstance(xi, (int, float))]
    if len(pairs) < 30:
        return None
    pos = [xi for xi, yi in pairs if yi == 1]
    neg = [xi for xi, yi in pairs if yi == 0]
    if not pos or not neg:
        return None
    # rank all values; sum of ranks of positives → U → AUC
    order = sorted(range(len(pairs)), key=lambda i: pairs[i][0])
    ranks = [0.0] * len(pairs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and pairs[order[j + 1]][0] == pairs[order[i]][0]:
            j += 1
        avg = (i + j) / 2 + 1  # average rank for ties, 1-based
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    r_pos = sum(ranks[idx] for idx, (_, yi) in enumerate(pairs) if yi == 1)
    n_pos, n_neg = len(pos), len(neg)
    u = r_pos - n_pos * (n_pos + 1) / 2
    return u / (n_pos * n_neg)
