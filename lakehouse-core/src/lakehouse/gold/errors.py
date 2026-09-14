"""Refusal reasons for the Gold layer.

Every Gold function is **fail-closed**: when it cannot prove that a transformation preserves
the meaning of the data, it raises instead of producing a number. The exception carries a
machine-readable ``reason`` so the agent layer can tell "I refuse and here is why" apart from
"something broke", and can decide whether to ask the user rather than guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


GOLD_REFUSAL_REASONS: Final[frozenset[str]] = frozenset(
    {
        "SERIES_NOT_CATALOGUED",
        "UNVERIFIED_SEMANTICS",
        "INACTIVE_SERIES",
        "UNSUPPORTED_MEASURE_TYPE",
        "MISSING_AGGREGATION_RULE",
        "UNSUPPORTED_AGGREGATION_RULE",
        "UPSAMPLING_REFUSED",
        "UNSUPPORTED_TARGET_FREQUENCY",
        "UNSUPPORTED_SOURCE_FREQUENCY",
        "AMBIGUOUS_VINTAGE",
        "DECOMPOSITION_REQUIRED",
        "NOT_DECOMPOSABLE",
        "MISSING_CUMULATIVE_RESET",
        "NO_OBSERVATIONS",
        "PERIOD_GRAIN_CONFLICT",
        "INVALID_ARGUMENT",
    }
)
"""Closed vocabulary of refusal reasons. Anything else is a bug, not a policy decision."""


@dataclass(frozen=True)
class GoldRefusal:
    """Why a Gold transformation refused to produce a value."""

    reason: str
    message: str
    series_id: str | None = None

    def __post_init__(self) -> None:
        if self.reason not in GOLD_REFUSAL_REASONS:
            raise ValueError(f"unsupported Gold refusal reason: {self.reason!r}")
        if not self.message.strip():
            raise ValueError("refusal message must not be empty")


class GoldError(ValueError):
    """Raised when Gold refuses to transform data it cannot vouch for."""

    def __init__(self, refusal: GoldRefusal) -> None:
        self.refusal = refusal
        location = f" [{refusal.series_id}]" if refusal.series_id else ""
        super().__init__(f"{refusal.reason}{location}: {refusal.message}")


def refuse(
    reason: str, message: str, *, series_id: str | None = None
) -> GoldError:
    """Build a refusal without repeating the wrapper at every call site."""

    return GoldError(GoldRefusal(reason=reason, message=message, series_id=series_id))


__all__ = ["GOLD_REFUSAL_REASONS", "GoldError", "GoldRefusal", "refuse"]
