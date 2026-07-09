"""Auditor signature check: temporal leakage in a train/test split.

The #1 way a backtest lies: rows from AFTER the cutoff leak into training (or the split
is random instead of time-ordered), so the model 'sees the future'. A dashboard then
shows +40% ROI that evaporates live.

This check takes the timestamps assigned to train vs test and detects:
  - overlap: test rows dated at/after cutoff that also appear in train,
  - order violation: train rows dated AFTER test rows (random-split fingerprint).

Pure function over timestamps; no DataHub dependency.
"""
from __future__ import annotations

from typing import Sequence

from .base import Check, Finding, Severity


class TemporalLeakageCheck(Check):
    id = "temporal_leakage"

    def run(
        self,
        train_ts: Sequence[float],
        test_ts: Sequence[float],
        *,
        max_overlap_ratio: float = 0.0,
    ) -> Finding:
        if not train_ts or not test_ts:
            return Finding(self.id, Severity.OK, "no split provided")

        train_max = max(train_ts)
        test_min = min(test_ts)
        # order violation: any train row later than the earliest test row
        leaked = [t for t in train_ts if t >= test_min]
        leak_ratio = len(leaked) / len(train_ts)

        if leak_ratio > max_overlap_ratio:
            return Finding(
                self.id,
                Severity.FAIL,
                "TEMPORAL LEAKAGE — training data overlaps the test period",
                detail=(
                    f"{len(leaked)}/{len(train_ts)} ({leak_ratio:.1%}) training rows are dated at/after "
                    f"the earliest test row. Split is not a clean time cut "
                    f"(train_max={train_max:.0f} ≥ test_min={test_min:.0f}); "
                    f"looks like a RANDOM split masquerading as walk-forward."
                ),
                metrics={"leak_ratio": leak_ratio, "train_max": train_max, "test_min": test_min},
                suggested_tags=["audit-failed", "temporal-leakage"],
                suggested_incident=True,
            )
        return Finding(
            self.id,
            Severity.OK,
            "clean temporal split (train strictly precedes test)",
            metrics={"train_max": train_max, "test_min": test_min},
        )
