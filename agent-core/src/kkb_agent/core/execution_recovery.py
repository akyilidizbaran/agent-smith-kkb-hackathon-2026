"""Bounded execution recovery and availability semantics for tool turns.

This module deliberately builds on the existing ``ToolError`` contract.  It
does not decide which SQL or catalog identifier is correct; it records what
failed, whether a fresh plan is still justified, and whether absence was
actually verified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .errors import ToolError

AvailabilityStatus = Literal[
    "FOUND",
    "CONFIRMED_ABSENT",
    "RETRIEVAL_FAILED",
    "ACCESS_BLOCKED",
    "UNSUPPORTED",
    "UNKNOWN",
]
FailureClass = Literal[
    "query_execution",
    "invalid_arguments",
    "semantic_guard",
    "reference_resolution",
    "join_alignment",
    "transient_provider",
    "access",
    "loop_guard",
    "other",
]

RECOVERABLE_CODES = frozenset({
    "SQL_FAILED",
    "INVALID_ARGS",
    "GOLD_REQUIRED",
    "JOIN_MISMATCH",
    "DATASET_NOT_FOUND",
    "TOOL_FAILED",
    "UNKNOWN_TOOL",
    "EMPTY_RESULT",
    "GEOGRAPHY_MISMATCH",
    # SOURCE_MISMATCH RECOVERABLE DEĞİL: bu hata, modelin SABİT/kapsam-içi kaynağın DIŞINA çıkmaya
    # çalıştığı anlamına gelir. Farklı bir kapsam-dışı adresle yeniden denemek sonucu değiştirmez
    # (pin değişmez); tekrar planlama turu boşa gider (Q9: aynı çıkmaz 3 kez denendi). İlk seferde
    # sonlanıp dürüst cevaba geçilir. Kapsam-içi kalan başarılı akışlar (Q1/Q8) bu kodu hiç üretmez.
})
ACCESS_CODES = frozenset({"NEEDS_CREDENTIAL", "ACCESS_BLOCKED", "SOURCE_NOT_FOUND"})
ABSENCE_CODES = frozenset({"OUT_OF_COVERAGE"})
_RETRY_REQUEST = re.compile(
    r"\b(?:tekrar\s+(?:dene|çek|cek)|yeniden\s+(?:çek|cek|dene)|bir\s+daha\s+(?:dene|çek|cek)|retry)\b",
    re.IGNORECASE,
)
_ABSENCE_LANGUAGE = re.compile(
    r"(?:bulunmuyor|bulunamadı|mevcut değil|veri yok|erişilemiyor|ulaşılamıyor|"
    r"alınamadı|kullanılamıyor|yoktur|not found|unavailable|does not exist)",
    re.IGNORECASE,
)


def is_explicit_retry(question: str) -> bool:
    """Return true only for an intentional retry/resume request."""

    return bool(_RETRY_REQUEST.search(question or ""))


def classify_error(error: ToolError) -> FailureClass:
    code = error.error_code
    if code == "SQL_FAILED":
        return "query_execution"
    if code == "INVALID_ARGS":
        return "invalid_arguments"
    if code == "GOLD_REQUIRED":
        return "semantic_guard"
    if code == "JOIN_MISMATCH":
        return "join_alignment"
    if code == "DATASET_NOT_FOUND" or code in {"COLUMN_NOT_FOUND", "VALUE_NOT_FOUND"}:
        return "reference_resolution"
    if code in ACCESS_CODES:
        return "access"
    if code == "TOOL_FAILED":
        return "transient_provider" if error.is_retryable else "other"
    if code == "DUPLICATE_CALL":
        return "loop_guard"
    return "other"


def absence_verified(tool_name: str, error: ToolError, content: str = "") -> bool:
    """Only authoritative coverage/search evidence may prove absence."""

    if error.error_code in ABSENCE_CODES:
        return True
    if error.error_code != "DATASET_NOT_FOUND" or tool_name != "lakehouse_search":
        return False
    lower = (content or "").casefold()
    if "henüz yüklenmemiş" in lower or "henüz çekilmemiş" in lower or error.candidates:
        return False
    return error.layer == "reference"


def recoverable_error(tool_name: str, error: ToolError, *, attempts: int, repeated: bool = False) -> bool:
    """Whether one more fresh planner turn is warranted for this failure."""

    if repeated or attempts >= ExecutionState.MAX_RECOVERY_ATTEMPTS:
        return False
    if absence_verified(tool_name, error):
        return False
    if error.error_code in ACCESS_CODES or error.error_code in {"UNSAFE_SQL", "GOLD_STALE"}:
        return False
    return error.error_code in RECOVERABLE_CODES


@dataclass(frozen=True)
class FailureObservation:
    failure_class: FailureClass
    tool_name: str
    error_code: str
    retryable: bool
    recovery_attempt: int
    repeated: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "failure_class": self.failure_class,
            "tool_error_code": self.error_code,
            "tool_name": self.tool_name,
            "retryable": self.retryable,
            "recovery_attempt": self.recovery_attempt,
            "same_call_repeated": self.repeated,
        }


@dataclass
class ExecutionState:
    """Mutable state for one user turn; no pending tool calls cross this object."""

    MAX_RECOVERY_ATTEMPTS = 3
    turn_id: int
    question: str
    availability_status: AvailabilityStatus = "UNKNOWN"
    failures: list[FailureObservation] = field(default_factory=list)
    recovery_prompts: int = 0
    pending_recovery: bool = False
    same_call_repeated: bool = False
    _recovery_signatures: list[tuple[str, str]] = field(default_factory=list)

    def observe_failure(
        self,
        tool_name: str,
        error: ToolError,
        *,
        signature: tuple[str, str] | None = None,
        repeated: bool = False,
        content: str = "",
    ) -> None:
        if signature is not None and signature not in self._recovery_signatures and not repeated:
            self._recovery_signatures.append(signature)
        self.same_call_repeated = self.same_call_repeated or repeated
        if absence_verified(tool_name, error, content):
            self.availability_status = "CONFIRMED_ABSENT"
        elif error.error_code in ACCESS_CODES:
            self.availability_status = "ACCESS_BLOCKED"
        elif error.error_code in RECOVERABLE_CODES and self.availability_status != "FOUND":
            self.availability_status = "RETRIEVAL_FAILED"
        attempt = len(self.failures) + 1
        observation = FailureObservation(
            failure_class=classify_error(error),
            tool_name=tool_name,
            error_code=error.error_code,
            retryable=error.is_retryable,
            recovery_attempt=attempt,
            repeated=repeated,
        )
        self.failures.append(observation)
        self.pending_recovery = recoverable_error(
            tool_name, error, attempts=attempt, repeated=repeated
        )

    def observe_success(self, *, data_produced: bool) -> None:
        if data_produced:
            self.availability_status = "FOUND"
            self.pending_recovery = False

    def observe_availability(self, status: str | None, tool_name: str, signature: tuple[str, str]) -> None:
        """Consume a structured semantic result that is not an error envelope."""
        if status == "CONFIRMED_ABSENT":
            self.availability_status = "CONFIRMED_ABSENT"
            self.pending_recovery = False
            return
        if status != "RETRIEVAL_FAILED" or self.availability_status == "FOUND":
            return
        self.availability_status = "RETRIEVAL_FAILED"
        if signature not in self._recovery_signatures:
            self._recovery_signatures.append(signature)
        attempt = len(self.failures) + 1
        self.failures.append(
            FailureObservation(
                failure_class="query_execution",
                tool_name=tool_name,
                error_code="EMPTY_RESULT",
                retryable=True,
                recovery_attempt=attempt,
            )
        )
        self.pending_recovery = attempt < self.MAX_RECOVERY_ATTEMPTS

    def should_prompt_recovery(self) -> bool:
        return self.pending_recovery and self.recovery_prompts < self.MAX_RECOVERY_ATTEMPTS

    def mark_recovery_prompted(self) -> None:
        self.recovery_prompts += 1
        self.pending_recovery = False

    def allow_next_failure_recovery(self) -> None:
        self.pending_recovery = True

    def snapshot(self) -> RecoverySnapshot:
        return RecoverySnapshot(
            question=self.question,
            failed_signatures=tuple(self._recovery_signatures),
            availability_status=self.availability_status,
        )

    def artifact(self, *, finalization_reason: str, resumed_previous_task: bool) -> dict[str, object]:
        status: AvailabilityStatus = self.availability_status
        if self.failures and status == "UNKNOWN":
            status = "RETRIEVAL_FAILED"
        return {
            "kind": "execution_recovery",
            "turn_id": self.turn_id,
            "failure_class": self.failures[-1].failure_class if self.failures else None,
            "tool_error_code": self.failures[-1].error_code if self.failures else None,
            "retryable": self.failures[-1].retryable if self.failures else None,
            "recovery_attempt": len(self.failures),
            "recovery_action": "replan" if self.failures and status != "FOUND" else "none",
            "same_call_repeated": self.same_call_repeated,
            "availability_status": status,
            "finalization_reason": finalization_reason,
            "resumed_previous_task": resumed_previous_task,
            "failures": [failure.as_dict() for failure in self.failures],
        }


@dataclass(frozen=True)
class RecoverySnapshot:
    question: str
    failed_signatures: tuple[tuple[str, str], ...] = ()
    availability_status: AvailabilityStatus = "RETRIEVAL_FAILED"


def needs_truthful_failure_text(text: str, state: ExecutionState) -> bool:
    """Reject absence wording when only a recoverable attempt failed."""

    return (
        state.availability_status == "RETRIEVAL_FAILED"
        and bool(state.failures)
        and not any(f.failure_class == "access" for f in state.failures)
        and bool(_ABSENCE_LANGUAGE.search(text or ""))
    )


__all__ = [
    "AvailabilityStatus",
    "ExecutionState",
    "FailureObservation",
    "RecoverySnapshot",
    "absence_verified",
    "classify_error",
    "is_explicit_retry",
    "needs_truthful_failure_text",
    "recoverable_error",
]
