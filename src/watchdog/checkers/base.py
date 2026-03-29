"""Base checker types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Single check outcome."""

    success: bool
    response_time_ms: float | None = None
    status_code: int | None = None
    error: str | None = None


class Checker(ABC):
    """Abstract monitor checker."""

    @abstractmethod
    async def check(self, target: str) -> CheckResult:
        """Execute single check."""
