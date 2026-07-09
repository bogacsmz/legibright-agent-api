"""Check framework: every Sentinel/Auditor check returns a Finding.

Checks are pure functions over data (arrays / row dicts). They know NOTHING about
DataHub — that keeps the statistical core unit-testable and honest. The agent layer
maps Findings to graph write-backs (tags/assertions/incidents).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


class Verdict(str, Enum):
    """Auditor's headline verdict for a metric/claim."""

    TRUSTWORTHY = "TRUSTWORTHY"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_TRUSTWORTHY = "NOT_TRUSTWORTHY"


@dataclass
class Finding:
    check: str                      # check id, e.g. "freshness", "temporal_leakage"
    severity: Severity
    headline: str                   # one line a judge/engineer reads first
    detail: str = ""                # the evidence / numbers
    metrics: dict[str, Any] = field(default_factory=dict)
    # write-back hints (the agent decides what actually lands on the graph)
    suggested_tags: list[str] = field(default_factory=list)
    suggested_incident: bool = False

    @property
    def failed(self) -> bool:
        return self.severity is Severity.FAIL


class Check:
    """Base class. Subclasses implement run(...) -> Finding."""

    id: str = "check"

    def run(self, *args, **kwargs) -> Finding:  # pragma: no cover
        raise NotImplementedError
