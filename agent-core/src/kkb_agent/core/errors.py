"""Yapılandırılmış araç hataları.

Hata, harness'ın en çok konuştuğu şeydir: model yanlış argüman verir, olmayan bir
seri ister, kapsam dışı dönem sorar. Bugüne kadar bunların hepsi serbest metindi —
21 ayrı noktada, her biri kendi cümlesiyle. Bu üç şeyi imkânsız kılıyordu:

  1. **Sayamıyorduk.** "Hangi hata kaç kez oluyor" sorusunun cevabı yoktu; golden
     çıktısında yalnız "3 araç hatası" yazıyordu. Araç sayısı arttıkça hangi sınıfın
     bozulduğunu görmek gerekiyor.
  2. **Ayıramıyorduk.** "Filtreyi düzelt, tekrar dene" ile "bu veri yok, tekrar
     deneme" aynı biçimde dönüyordu. Modelin ikisini üsluptan ayırması gerekiyordu;
     ADR-0017'de ölçtük, ayıramıyor.
  3. **Yönlendiremiyorduk.** Adaylar (mevcut kolonlar, benzer seriler) mesajın içine
     gömülüydü; yapısal olarak taşınmıyordu.

`ToolError` bu üçünü çözer. Mesaj metinleri olduğu gibi korunur — ölçülerek
yazıldılar (ADR-0010, 0016, 0017, 0019); değişen, etraflarındaki zarf.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Hata sınıfları. Yeni bir kod eklemek, harness'ın onu sayabilmesi ve
# onarılabilirliğine karar verebilmesi demektir.
ErrorCode = Literal[
    # şema katmanı — argümanın şekli
    "INVALID_ARGS",
    "UNKNOWN_TOOL",
    # referans katmanı — argüman var olan bir şeye mi işaret ediyor
    "DATASET_NOT_FOUND",
    "COLUMN_NOT_FOUND",
    "VALUE_NOT_FOUND",
    # politika katmanı — izin veriliyor mu
    "UNSAFE_SQL",
    "MISSING_PERIOD_FILTER",
    # Gold katmanının semantik reddi: katalog kuralı bu dönüşümü güvenli bulmuyor
    # (stok seride decompose, doğrulanmamış semantik, üst örnekleme...). Kural
    # kataloğun, seçim modelin değil (ADR-0031).
    "GOLD_REFUSED",
    # veri katmanı — sorgu çalıştı, sonuç ne söylüyor
    "OUT_OF_COVERAGE",
    "EMPTY_RESULT",
    "JOIN_MISMATCH",
    # çalışma alanı
    "NO_ACTIVE_TABLE",
    "COLUMN_EXISTS",
    # harness
    "DUPLICATE_CALL",
    "TOOL_FAILED",
    "SQL_FAILED",
    # erişim katmanı — kaynağa ulaşılabildi mi (ADR-0028)
    "NEEDS_CREDENTIAL",
    "ACCESS_BLOCKED",
    "SOURCE_NOT_FOUND",
]

#: Tekrar denemenin sonucu değiştirmeyeceği hatalar. Bunlar modele "düzelt ve
#: tekrar dene" olarak değil, "bu yoldan sonuç çıkmaz" olarak gider; harness
#: araçsız bir cevap turuna geçer.
NOT_RETRYABLE: frozenset[str] = frozenset({
    "OUT_OF_COVERAGE",   # veri yok; kaç kez sorulursa sorulsun yok
    "UNSAFE_SQL",        # politika; farklı yazımı denemek sınırı aşma girişimi olur
    "UNKNOWN_TOOL",      # var olmayan araç
    # Aynı kaynağı aynı biçimde tekrar istemek sonucu değiştirmez; alternatif
    # kaynak ayrı bir çağrıdır ve kararı harness verir (access_policy.decide).
    "NEEDS_CREDENTIAL",
    "ACCESS_BLOCKED",
    "SOURCE_NOT_FOUND",
    "GOLD_REFUSED",      # kural katalogda; aynı çağrıyı tekrarlamak kuralı değiştirmez
})


@dataclass
class ToolError:
    """Bir araç çağrısının neden başarısız olduğunun yapılandırılmış anlatımı."""

    error_code: ErrorCode
    message: str
    hint: str | None = None
    candidates: list[str] = field(default_factory=list)
    layer: Literal["schema", "reference", "policy", "data", "workspace", "harness", "access"] = "data"
    retryable: bool | None = None  # None → NOT_RETRYABLE tablosuna bak

    @property
    def is_retryable(self) -> bool:
        if self.retryable is not None:
            return self.retryable
        return self.error_code not in NOT_RETRYABLE

    def render(self) -> str:
        """Modele giden metin.

        Kod köşeli parantezde: modelin okuması için değil, trace ve ölçüm için.
        Model asıl mesajı ve YAPACAĞIN satırını okur.
        """
        parts = [f"HATA[{self.error_code}]: {self.message}"]
        if self.candidates:
            shown = ", ".join(self.candidates[:8])
            more = f" (+{len(self.candidates) - 8} tane daha)" if len(self.candidates) > 8 else ""
            parts.append(f"ADAYLAR: {shown}{more}")
        if self.hint:
            parts.append(f"YAPACAĞIN: {self.hint}")
        if not self.is_retryable:
            parts.append(
                "BU HATA TEKRAR DENEMEYLE ÇÖZÜLMEZ. Aynı çağrıyı farklı biçimde deneme; "
                "kullanıcıya durumu açıkla."
            )
        return "\n".join(parts)
