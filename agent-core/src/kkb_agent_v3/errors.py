"""Tek hata zarfı — her araç, her katman aynı şekli döndürür.

Neden tek zarf: modele "HATA: ..." serbest metni dönünce onarım şansa kalıyor;
hangi hatanın tekrar denemeye değer olduğunu (retryable), hangisinin kullanıcıya
soru gerektirdiğini (needs_user_input) ve düzeltme için somut adayları
(candidates) harness bilir, model tahmin etmez. Aynı kalıp WrenAI'de
"structured errors with hints" olarak kullanılıyor [SRC]; kod listesi data
ekibinin LAKEHOUSE_CONTRACT_FILLED.md §18 zarfıyla birleşiktir.

Modele giden gözlem zarfın KISA özetidir (`observation()`); tam zarf trace'e
ve benchmark'ın hata-kodu dağılımına gider.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ErrorCode = Literal[
    # --- data ekibi sözleşmesi (§18) ---
    "SOURCE_UNAVAILABLE",
    "FETCH_TIMEOUT",
    "HTTP_ERROR",
    "UNSUPPORTED_FORMAT",
    "PARSE_FAILED",
    "SCHEMA_MISMATCH",
    "EMPTY_DATASET",
    "OBSERVATION_COUNT_MISMATCH",
    "QUALITY_FAILED",
    "SERIES_NOT_FOUND",
    "SERIES_NOT_MATERIALIZED",
    "SEMANTIC_VIOLATION",
    "UNSAFE_SQL",
    "QUERY_TIMEOUT",
    # --- motor katmanı (V3 §3.3) ---
    "INVALID_ARGS",        # şema katmanı: eksik/yanlış tipte alan
    "UNKNOWN_TOOL",        # kayıtlı olmayan araç adı
    "COLUMN_NOT_FOUND",    # referans katmanı: kolon workspace'te/katalogda yok
    "OUT_OF_COVERAGE",     # referans katmanı: istenen dönem first_obs..last_obs dışında
    "DOUBLE_COUNT",        # referans katmanı: alt toplam + bileşen aynı toplamda
    "MISSING_PERIOD_FILTER",  # soruda yıl var, sorguda yok (ADR-0017)
    "WORKSPACE_EMPTY",     # tablo yokken tablo üstünde işlem
    "POLICY_VIOLATION",    # politika katmanı: index kilidi, side-effect, limit
    "TOOL_FAILED",         # araç çalışırken beklenmeyen istisna
    "DUPLICATE_CALL",      # harness: aynı araç + aynı argüman zaten başarıyla çalıştı (döngü kilidi)
]

# Kod → varsayılan retry davranışı. Araç gerekçesi varsa üzerine yazabilir.
# retryable=False olanlar modele geri dönmez; güvenli başarısızlık şablonuna gider.
DEFAULT_RETRYABLE: dict[str, bool] = {
    "UNSAFE_SQL": False,
    "POLICY_VIOLATION": False,
    "UNKNOWN_TOOL": True,
    "INVALID_ARGS": True,
    "SERIES_NOT_FOUND": True,
    "COLUMN_NOT_FOUND": True,
    "OUT_OF_COVERAGE": False,   # tekrar denemek veri üretmez; cevap "veri yok" olmalı
    "EMPTY_DATASET": True,
    "SEMANTIC_VIOLATION": True,
    "DOUBLE_COUNT": True,
    "MISSING_PERIOD_FILTER": True,
    "WORKSPACE_EMPTY": True,
    "TOOL_FAILED": True,
    "DUPLICATE_CALL": True,
    "QUERY_TIMEOUT": True,
    "SOURCE_UNAVAILABLE": False,
    "FETCH_TIMEOUT": True,
    "HTTP_ERROR": True,
    "UNSUPPORTED_FORMAT": False,
    "PARSE_FAILED": False,
    "SCHEMA_MISMATCH": True,
    "OBSERVATION_COUNT_MISMATCH": True,
    "QUALITY_FAILED": False,
    "SERIES_NOT_MATERIALIZED": False,
}


class ToolError(BaseModel):
    """Yapılandırılmış araç hatası. Araçlar `ToolResult.fail(ToolError(...))` döndürür."""

    error_code: ErrorCode
    message: str = Field(description="Kısa, Türkçe, modelin okuyacağı açıklama")
    hint: str | None = Field(default=None, description="Düzeltme için somut yönlendirme")
    candidates: list[str] = Field(
        default_factory=list, description="En yakın adaylar (seri/kolon/değer); en fazla 3-5"
    )
    retryable: bool | None = Field(
        default=None, description="None ise DEFAULT_RETRYABLE[error_code] geçerli"
    )
    needs_user_input: bool = Field(
        default=False, description="Model değil kullanıcı çözebilir → clarify yoluna"
    )
    source_id: str | None = Field(default=None, description="Data ekibi zarfıyla uyum")
    layer: Literal["schema", "reference", "policy", "runtime"] | None = None

    @property
    def is_retryable(self) -> bool:
        if self.retryable is not None:
            return self.retryable
        return DEFAULT_RETRYABLE.get(self.error_code, True)

    def observation(self) -> str:
        """Modele dönen tek paragraf. Zarfın tamamı değil; kod + mesaj + ipucu + adaylar."""
        parts = [f"{self.error_code}: {self.message}"]
        if self.candidates:
            parts.append("Adaylar: " + " | ".join(self.candidates[:5]))
        if self.hint:
            parts.append("YAPACAĞIN: " + self.hint)
        if not self.is_retryable:
            parts.append("Bu hata tekrar denemeyle çözülmez; kullanıcıya durumu açıkla.")
        return "\n".join(parts)
