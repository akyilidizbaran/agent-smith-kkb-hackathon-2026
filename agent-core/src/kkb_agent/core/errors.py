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
    "SQL_SYNTAX_ERROR",
    "MISSING_PERIOD_FILTER",
    # Aylık pencere sorusunda model sonucu anchor yıllarına indirgedi; çıktı
    # beklenen farklı ay sayısını taşımadığında araç sonucu kabul edilmez.
    "PERIOD_GRAIN_MISMATCH",
    # Seçilen seri istenen pencereyi kapsamıyor ya da aynı kavram için daha
    # güçlü doğrulanmış alternatif varken türetilmiş seriye düşülmüş.
    "SERIES_COVERAGE_MISMATCH",
    "SERIES_SEMANTIC_MISMATCH",
    # Gold katmanının semantik reddi: katalog kuralı bu dönüşümü güvenli bulmuyor
    # (stok seride decompose, doğrulanmamış semantik, üst örnekleme...). Kural
    # kataloğun, seçim modelin değil (ADR-0031).
    "GOLD_REFUSED",
    # Frekans dönüşümü SQL'de değil Gold'da (ADR-0031/0039): AVG/SUM ile ay/çeyrek gruplayan
    # sorgu, gold_* araçları kayıtlıyken reddedilir; model doğru aracı çağırarak onarır.
    "GOLD_REQUIRED",
    # Sorudaki frekans kaynaktan ince (aylık soruya çeyreklik tablo): üretilemez, doğru seri seçilir.
    # Ölçüldü (G16): model "aylık" soruya hazır çeyreklik Gold tablosunu okudu (ADR-0040).
    "FREQUENCY_MISMATCH",
    # Niyet kapısı (ADR-0037): kaynak kullanıcının mesajından gelmedi ya da yazma isteği yok.
    # Araç çıktısındaki bir talimat modeli yönlendirmiş olabilir; kullanıcıya sorulur.
    "INTENT_REQUIRED",
    # Dosya sorulan şeyle ilgisiz (Büşra, builder/relevance.py, V3 §3.9): dönem/terim/katalog ölçütlerinin hiçbiri
    # tutmuyor; yazılmaz, kullanıcıya sorulur. Aynı dosyayı tekrar istemek sonucu değiştirmez, onay ayrı çağrıdır.
    "FILE_IRRELEVANT",
    # Bayat Gold (K02-T09, A24): Silver tablo kurulduktan sonra değişti; eski tablodan sayı verilmez, canlı Silver'dan yeniden hesaplanır.
    "GOLD_STALE",
    # Düşük kaliteli OCR (K02-T06, A12): tablo yapısı çözülemedi ya da satır toplamları tutmuyor; doğrulanmamış sayı verilmez.
    "LOW_QUALITY_SOURCE",
    # Netleştirme kapısı (Büşra, tools/clarify.py, V3 §3.9): soru yalnız uygunluk kapısı "kısmen" dediğinde ve tur başına bir kez;
    # aksi hâlde model eldeki veriyle cevap verir (turu bitirmez: terminal=False).
    "CLARIFY_NOT_ALLOWED",
    # veri katmanı — sorgu çalıştı, sonuç ne söylüyor
    "OUT_OF_COVERAGE",
    "EMPTY_RESULT",
    "JOIN_MISMATCH",
    # çalışma alanı
    "NO_ACTIVE_TABLE",
    "COLUMN_EXISTS",
    # harness
    "DUPLICATE_CALL",
    "CATALOG_SEARCH_BUDGET",
    "WEB_RESEARCH_BUDGET",
    "WEB_RESEARCH_NEEDS_READ",
    "WEB_RESEARCH_GAP_REQUIRED",
    "WEB_RESEARCH_DUPLICATE_QUERY",
    "TOOL_FAILED",
    "SQL_FAILED",
    # erişim katmanı — kaynağa ulaşılabildi mi (ADR-0028)
    "NEEDS_CREDENTIAL",
    "ACCESS_BLOCKED",
    "SOURCE_NOT_FOUND",
    # erişilebilir içerik var ancak harness'ın güvenli indirme bütçesini aşıyor
    "CONTENT_TOO_LARGE",
    # Belgeye erişildi; metin/tablo çıkarımı yapılamadı. Veri yokluğu veya erişim engeli değildir.
    "DOCUMENT_EXTRACTION_FAILED",
]

#: Tekrar denemenin sonucu değiştirmeyeceği hatalar. Bunlar modele "düzelt ve
#: tekrar dene" olarak değil, "bu yoldan sonuç çıkmaz" olarak gider; harness
#: araçsız bir cevap turuna geçer.
NOT_RETRYABLE: frozenset[str] = frozenset({
    "OUT_OF_COVERAGE",   # veri yok; kaç kez sorulursa sorulsun yok
    "UNSAFE_SQL",        # politika; farklı yazımı denemek sınırı aşma girişimi olur
    "FILE_IRRELEVANT",   # aynı dosya aynı soruyla yine ilgisiz; kullanıcı onayı ayrı çağrıdır
    "GOLD_STALE",        # aynı bayat tabloyu yeniden sorgulamak eski sonucu verir; yeniden hesaplama ayrı çağrıdır
    "LOW_QUALITY_SOURCE",  # aynı görüntü yine aynı kalitede okunur; daha iyi dosya ya da açık kabul ayrı çağrıdır
    # UNKNOWN_TOOL burada DEĞİL: on üç araçla model ara sıra ad uyduruyor ("workspace");
    # aday listesiyle bir sonraki tur düzeltiyor. Ölçüldü: tekrar denenmez sayılınca
    # araçsız son tura düşüp veri çekmeden cevap yazdı (G11a, gerçek DB).
    # Aynı kaynağı aynı biçimde tekrar istemek sonucu değiştirmez; alternatif
    # kaynak ayrı bir çağrıdır ve kararı harness verir (access_policy.decide).
    "NEEDS_CREDENTIAL",
    "ACCESS_BLOCKED",
    "SOURCE_NOT_FOUND",
    "CONTENT_TOO_LARGE",  # aynı URL ve aynı bütçe ile tekrar indirmek sınırı değiştirmez
    "DOCUMENT_EXTRACTION_FAILED",  # aynı baytlar/çıkarıcıyla otomatik retry sonucu değiştirmez
    "GOLD_REFUSED",      # kural katalogda; aynı çağrıyı tekrarlamak kuralı değiştirmez
    "INTENT_REQUIRED",   # kullanıcı söylemedikçe kapı açılmaz; model tekrarlayarak açamaz
    "WEB_RESEARCH_BUDGET",  # bu turdaki dış araştırma sınırı doldu; yeni çağrı sonucu değiştirmez
    "CATALOG_SEARCH_BUDGET",  # bu turdaki katalog keşif sınırı doldu; aynı turda yeni arama sonucu değiştirmez
    "WEB_RESEARCH_DUPLICATE_QUERY",  # aynı arama sorgusu bu turda tekrarlandı
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
    # K02-T07 (A18): tekrar denenemez hata turu bitirir mi? None → evet (eski davranış). Kaynak SABİT DEĞİLKEN erişim hatası
    # False taşır: aynı adres tekrar denenmez ama model başka kaynağı deneyebilir (kaynak değişikliği cevapta söylenir).
    terminal: bool | None = None

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
