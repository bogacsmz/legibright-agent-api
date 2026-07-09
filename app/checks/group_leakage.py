"""Auditor check: group leakage — the same entity in both train and test.

A temporal split can still leak if the same entity (customer, team, horse, user) appears in
both train and test: the model memorizes the entity, not the pattern, and the holdout is
contaminated. This check takes the group/entity ids of the train and test rows and flags
overlap. Independent of timestamps and of the split SQL.
"""
from __future__ import annotations

from typing import Sequence

from .base import Check, Finding, Severity


class GroupLeakageCheck(Check):
    id = "group_leakage"

    def run(
        self,
        train_groups: Sequence,
        test_groups: Sequence,
        *,
        overlap_warn: float = 0.0,
        overlap_fail: float = 0.10,
        entity: str = "entity",
    ) -> Finding:
        tr, te = set(train_groups), set(test_groups)
        if not te:
            return Finding(self.id, Severity.OK, "group leakage: no test groups to check")
        overlap = tr & te
        ratio = len(overlap) / len(te)
        detail = (f"{len(overlap)}/{len(te)} test {entity} values ({ratio:.0%}) also appear in "
                  f"training; e.g. {sorted(map(str, overlap))[:5]}")

        if ratio > overlap_fail:
            return Finding(self.id, Severity.FAIL,
                           f"GROUP LEAKAGE — {ratio:.0%} of test {entity}s are also in train",
                           detail=detail, metrics={"overlap_ratio": ratio, "overlap": len(overlap)},
                           suggested_tags=["audit-failed", "group-leakage"], suggested_incident=True)
        if ratio > overlap_warn:
            return Finding(self.id, Severity.WARN,
                           f"minor group overlap ({ratio:.0%} of test {entity}s in train)",
                           detail=detail, metrics={"overlap_ratio": ratio},
                           suggested_tags=["audit-warn"])
        return Finding(self.id, Severity.OK, f"no {entity} overlap between train and test")
