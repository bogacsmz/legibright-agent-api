"""Service-level input error → mapped to a helpful HTTP 400."""
from __future__ import annotations


class InvalidInput(Exception):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field
