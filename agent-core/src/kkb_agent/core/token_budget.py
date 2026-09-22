"""Çağrı amacına göre LLM çıktı bütçesi seçimi.

`LLM_MAX_TOKENS` geriye dönük olarak bütün çağrılar için üst sınır olarak
korunur. Ancak katalog keşfi için gereken kısa araç kararını, uzun anlatı ile
aynı tavanla göndermek sağlayıcıda gereksiz gecikme yaratabilir. Bu modül,
çağrının fazına göre daha küçük bir hedef seçer ve global tavanı aşmaz.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenBudgetPolicy:
    """Tek soru içindeki LLM çağrıları için deterministik token politikası.

    Değerler completion token tavanıdır. `global_max` mevcut
    ``LLM_MAX_TOKENS`` ayarının geriye dönük uyumluluk tavanıdır; pozitifse tüm
    fazları kısar, ``None`` ise faz değerleri sınırsız bırakılır.
    """

    global_max: int | None = None
    planning: int = 1000
    tool: int = 1800
    narration: int = 2800
    long_narration: int = 3400
    recovery: int = 1400
    long_rows: int = 48
    long_columns: int = 6

    def __post_init__(self) -> None:
        for name in ("planning", "tool", "narration", "long_narration", "recovery"):
            value = getattr(self, name)
            if value <= 0:
                raise ValueError(f"{name} token bütçesi pozitif olmalı: {value}")
        if self.global_max is not None and self.global_max <= 0:
            raise ValueError(f"global_max pozitif olmalı: {self.global_max}")

    def for_phase(
        self,
        phase: str,
        *,
        rows: int = 0,
        columns: int = 0,
        extended_narration: bool | None = None,
    ) -> int | None:
        """Choose a completion ceiling by phase and narration complexity.

        ``extended_narration`` is the preferred signal: table size belongs to
        the UI artifact and should not, by itself, buy the model a larger
        prose budget. The row/column thresholds remain as a compatibility
        fallback for callers that have not supplied a task-complexity signal.
        """
        if phase == "planning":
            target = self.planning
        elif phase == "tool":
            target = self.tool
        elif phase == "recovery":
            target = self.recovery
        elif phase == "narration":
            is_extended = (
                extended_narration
                if extended_narration is not None
                else rows >= self.long_rows or columns >= self.long_columns
            )
            target = self.long_narration if is_extended else self.narration
        else:
            raise ValueError(f"bilinmeyen token bütçesi fazı: {phase!r}")
        return min(target, self.global_max) if self.global_max is not None else target
