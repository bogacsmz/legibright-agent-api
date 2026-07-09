"""Auditor check: overfit red flags on a reported metric. Domain-agnostic.

The tell of overfit is NOT a modest train/test gap — a good model can have a real gap and
still generalize (bike-sharing Ridge: R² 0.79→0.57 is healthy, holdout carries real signal).
The tell is one of:

  * near-perfect in-sample on a BOUNDED metric (accuracy/R²/AUC ≥ ~0.95) — memorization,
  * a large gap PAIRED with that near-perfect in-sample,
  * holdout collapse (ROI-like metric goes ≤ 0 out of sample),
  * multiple-testing luck (N cells scanned → expected false winners),
  * (opt-in) an implausible absolute value for unbounded metrics, e.g. flat ROI > 20%.

So a legitimate model with a moderate gap PASSES; an unpruned tree at 0.99 train FAILS.
"""
from __future__ import annotations

from .base import Check, Finding, Severity

_NEAR_PERFECT = 0.95
_MEMORIZING = 0.90
_COLLAPSE_GAP = 0.25   # a train→holdout drop this large is overfit regardless of level


class OverfitFlagsCheck(Check):
    id = "overfit_flags"

    def run(
        self,
        *,
        in_sample: float,
        holdout: float | None = None,
        n_cells_scanned: int = 1,
        gap_alarm: float = 0.10,
        abs_alarm: float | None = None,   # set for unbounded ROI-like metrics
        bounded: bool = True,             # accuracy/R²/AUC are bounded at 1.0
        metric: str = "score",
    ) -> Finding:
        flags: list[str] = []
        fail = False
        gap = None if holdout is None else in_sample - holdout

        # unbounded ROI-like: implausible absolute value + holdout collapse
        if abs_alarm is not None and in_sample > abs_alarm:
            flags.append(f"in-sample {metric} {in_sample:.2f} > {abs_alarm:.2f} implausibility alarm")
            if holdout is not None and holdout <= 0:
                fail = True
                flags.append(f"holdout {metric} collapsed to {holdout:.2f}")

        # bounded metric: two independent overfit tells
        if bounded and gap is not None and gap > gap_alarm:
            if gap > _COLLAPSE_GAP:
                # a large train→holdout collapse is overfit at ANY in-sample level
                # (catches 0.93→0.40 and 0.95→0.10, not just near-perfect memorization)
                fail = True
                flags.append(f"holdout collapse: {metric} {in_sample:.3f}→{holdout:.3f} "
                             f"(gap {gap:+.3f} > {_COLLAPSE_GAP})")
            elif in_sample >= _NEAR_PERFECT:
                fail = True
                flags.append(f"near-perfect in-sample {metric} {in_sample:.2f} with "
                             f"{in_sample:.2f}→{holdout:.2f} drop (gap {gap:+.2f}) — memorization")
            elif in_sample >= _MEMORIZING:
                flags.append(f"borderline: in-sample {metric} {in_sample:.2f}, gap {gap:+.2f}")
            # else: modest gap on a non-memorizing model → NOT flagged (generalizes)

        if n_cells_scanned > 1 and n_cells_scanned * 0.023 >= 1:
            flags.append(f"{n_cells_scanned} cells scanned → ~{n_cells_scanned*0.023:.1f} "
                         "expected false z≥2 winners")

        if not flags:
            return Finding(self.id, Severity.OK, f"no overfit red flags ({metric} generalizes)",
                           metrics={"in_sample": in_sample, "holdout": holdout, "gap": gap})
        sev = Severity.FAIL if fail else Severity.WARN
        return Finding(
            self.id, sev, "OVERFIT RED FLAGS present", detail="; ".join(flags),
            metrics={"in_sample": in_sample, "holdout": holdout, "gap": gap, "n_cells": n_cells_scanned},
            suggested_tags=["audit-failed"] if fail else ["audit-warn"],
        )


