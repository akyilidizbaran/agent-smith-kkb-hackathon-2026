"""Tur niyeti: kullanıcının sorusu turun başında bir kez sınıflandırılır (ADR-0104).

Önceden bu desenler `core/agent.py` içinde dağınıktı ve her kontrol ham soru metnini kendisi okuyordu. İki niyet aynı
soruda buluşunca (ör. "kaynak" kelimesi geçen bir dönüşüm isteği) hangisinin geçerli olduğunu kimse bilmiyordu; DeepSeek
76 vakalık koşuda 9 tur bu yüzden istenmeyen kaynak özeti aldı. Artık bütün kontroller `classify(question)` sonucunu
okur; öncelik kuralları burada, tek yerde durur. Desenler ölçüme dayandığı için değiştirilmeden taşındı.

Test: `tests/test_turn_intent.py` 76 benchmark sorusunun bütün turlarının sınıflandırmasını kilitler.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .question_preflight import _PREMISE as _PREMISE_ASK
from .source_summary import is_source_question

# Kullanıcının grafik isteği (Türkçe çekimli: grafiği, grafiğini, çiz, çizer misin, görselleştir).
_CHART_ASK = re.compile(r"grafi|çiz|gorselle|görselle|\bplot\b|\bchart\b|harita", re.I)
# Analitik isteği: aykırılık / kırılma / öncülük (ADR-0040). Araç çalışmadan iddia yazılmaz.
_ANALYTICS_ASK = re.compile(r"anomali|aykır|sapan|sapma|olağan ?dışı|sıra ?dışı|kırılma|rejim değişi|öncül|önden mi|korelasyon|granger|mevsimsel|seasonal|\bmad\b|medyan mutlak", re.I)
# A table transformation request is distinct from a new retrieval request.
# These phrases describe work that must be performed on the verified active
# table (for example, monthly deltas and a common date axis), even when the
# user does not say "add a column" explicitly.
_TRANSFORMATION_ASK = re.compile(
    r"aylık\s+değiş|aylik\s+degis|değişim|degisim|yüzde\s+değiş|yuzde\s+degis|"
    r"analiz\s+etmeye\s+uygun|aynı\s+tarih\s+ekseni|aylık\s+bazda\s+hizala|"
    r"hizala|normalleştir|normalestir|dönüştür|donustur|"
    # Çıplak "oran/kolon/sütun" dönüşüm değildir (son 3×: P05 "oran serisini ara", F08 "kolonlar aynı olsun" dışa aktarma,
    # A06 kolon adı enjeksiyonu). Eylemle birlikte geçince dönüşümdür: "kolon ekle", "oranı hesapla".
    r"\b(?:sütun|sutun|kolon)\w*\s+(?:ekle|hesapla|oluştur|olustur|türet|turet)|"
    r"\boran\w*\s+(?:hesapla|türet|turet|oluştur|olustur)|"
    # "aylık farkı hesapla", "önceki aya göre mutlak fark" (F07/P02, DeepSeek 76 vaka): fark da bir dönüşümdür.
    # "farklı" (başka) eşleşmez: ekten sonra kelime sınırı aranır.
    r"\bfark(?:lar)?(?:ı|i|ın|in|ını|ini|a|ına|ine|da|dan|ta|tan)?\b|\bdiff(?:erence)?s?\b",
    re.I,
)
# A direct table delivery is already a complete answer when the user asks to
# retrieve/list/export data without asking for interpretation.  In that case
# the model's post-query "peek then narrate" turns only add latency; the
# structured table and downloads are the primary deliverable.
_TABLE_DELIVERY_ASK = re.compile(
    r"\b(getir|getirebilir|göster|goster|listele|sırala|sirala|sun|ver|dök|dok|aktar|indir|"
    r"get|show|list|fetch|retrieve|return|export|download|provide)\b|"
    r"tablo(?:yu|su| halinde| olarak)?",
    re.IGNORECASE,
)
_NARRATIVE_OR_ANALYSIS_ASK = re.compile(
    r"analiz|yorum|özet|ozet|açıkla|acikla|değerlendir|degerlendir|karşılaştır|karsilastir|"
    r"değişim|degisim|artış|artis|azalış|azalis|büyüme|buyume|trend|eğilim|egilim|"
    r"anomali|aykır|aykir|kırılma|kirilma|öncül|oncul|korelasyon|nedensel|neden|etkisi|"
    r"stok|akış|akis|birim|seri türü|seri tipi|neye göre|ilişki",
    re.IGNORECASE,
)
_EXPLICIT_INTERPRETATION_ASK = re.compile(
    r"\b(?:yorumla|açıkla|acikla|özetle|ozetle|değerlendir|degerlendir|"
    r"analiz\s+et|analizini\s+çıkar|analizini\s+cikar|bulguları\s+yorumla|"
    r"explain|interpret|summari[sz]e|analy[sz]e|insights?)\b|"
    r"\b(?:neden|niçin|nicin)\b",
    re.IGNORECASE,
)
# A comparison request wants prose about the result, not only the table.
# Measured (PR #18 jenerik, 21 Sep): transform/delivery fast paths answered
# comparison questions with two fixed sentences and no interpretation.
_COMPARISON_ASK = re.compile(
    r"karşılaştır|karsilastir|kıyasla|kiyasla|\bvs\b|yorumla|değerlendir|degerlendir", re.IGNORECASE,
)

# Veri silme/değiştirme ya da kişisel veri isteği (ADR-0105). Bu turlarda deterministik tablo teslimi devreye girmez;
# model isteğin o kısmını açıkça reddetmeli. Ölçüldü (ADR-0104 3 tekrar): A05 "tüm tabloları sil, sonra…", Q08 "DROP et",
# A08 "müşterilerin kişisel bilgilerini ekle" turlarında şablon teslim reddi yuttu.
_SENSITIVE_ASK = re.compile(
    r"\b(?:sil|silin|silip|silerek|sildir|drop|truncate|delete|temizle|yok\s+et|üzerine\s+yaz|update|insert|alter)\b|"
    r"kişisel\s+(?:bilgi|veri)|kisisel\s+(?:bilgi|veri)|müşteri\w*\s+(?:bilgi|isim|ad|kimlik|tc)|tc\s*kimlik|"
    r"\bpersonal\s+data\b|\bpii\b",
    re.I,
)

# Aynı turda hem mutlak fark hem yüzde değişim (ADR-0105, F04.2): deterministik hızlı yol tek işlem yapar; iki işlem
# istenince yalnız yüzdeyi hesaplıyordu. Bu turlarda hızlı yol devreye girmez, model iki kolonu da hesaplar.
_ABSOLUTE_CHANGE_ASK = re.compile(r"mutlak|\bfark(?:ı|i|ını|ini|lar|ları|lari)?\b|\babsolute\b|\bdifferences?\b", re.I)
_PERCENT_ASK = re.compile(r"%|yüzde|yuzde|percent(?:age)?|\bpct\b", re.I)

# Soruda dosya ya da adres (yükleme satırı "Dosya: …" veya URL).
_FILE_REF = re.compile(r"(?:^|\n)\s*Dosya:\s*\S+|https?://\S+", re.I)
# K03 hedefli canlı tekrar bulgusu (14 Eyl): birleştirme istenen turda model workspace_join çağırmadan anahtar eşleşmesi yazdı.
_JOIN_ASK = re.compile(r"birleştir|birlestir|eşleştir|eslestir|\bjoin\b", re.I)


@dataclass(frozen=True)
class TurnIntent:
    """Bir sorunun niyet bayrakları. `kind` yalnız özet etikettir (izleme ve test tablosu için); kararlar bayraklara bakar."""

    question: str
    chart: bool
    analytics: bool
    transformation: bool
    table_delivery: bool
    narrative_or_analysis: bool
    interpretation: bool
    comparison: bool
    premise: bool
    source_question: bool
    join: bool
    file_ref: bool
    sensitive: bool = False
    absolute_and_percent: bool = False

    @property
    def read_only_source(self) -> bool:
        """Yalnız saf kaynak sorusu deterministik kaynak özetiyle cevaplanır. Aynı soru tablo, dönüşüm ya da dışa aktarım da
        istiyorsa normal yol sürer: DeepSeek 76 vakalık koşuda 9 tur (F01/F03/F04/F07/F08, D04, I08, O07/O08) bu ayrım
        olmadığı için istenen sonuç yerine kaynak özeti aldı."""
        return self.source_question and not self.table_delivery and not self.transformation

    @property
    def kind(self) -> str:
        if self.read_only_source:
            return "kaynak"
        if self.interpretation or self.comparison:
            return "yorum"
        if self.analytics:
            return "analitik"
        if self.chart:
            return "grafik"
        if self.join:
            return "birleştirme"
        if self.transformation:
            return "dönüşüm"
        if self.table_delivery:
            return "tablo"
        return "diğer"

    def flags(self) -> dict[str, bool]:
        names = ("chart", "analytics", "transformation", "table_delivery", "narrative_or_analysis", "interpretation",
                 "comparison", "premise", "source_question", "join", "file_ref", "sensitive", "absolute_and_percent")
        return {name: getattr(self, name) for name in names} | {"read_only_source": self.read_only_source}


@lru_cache(maxsize=512)
def classify(question: str) -> TurnIntent:
    q = question or ""
    return TurnIntent(
        question=q,
        chart=bool(_CHART_ASK.search(q)),
        analytics=bool(_ANALYTICS_ASK.search(q)),
        transformation=bool(_TRANSFORMATION_ASK.search(q)),
        table_delivery=bool(_TABLE_DELIVERY_ASK.search(q)),
        narrative_or_analysis=bool(_NARRATIVE_OR_ANALYSIS_ASK.search(q)),
        interpretation=bool(_EXPLICIT_INTERPRETATION_ASK.search(q)),
        comparison=bool(_COMPARISON_ASK.search(q)),
        premise=bool(_PREMISE_ASK.search(q)),
        source_question=is_source_question(q),
        join=bool(_JOIN_ASK.search(q)),
        file_ref=bool(_FILE_REF.search(q)),
        sensitive=bool(_SENSITIVE_ASK.search(q)),
        absolute_and_percent=bool(_ABSOLUTE_CHANGE_ASK.search(q) and _PERCENT_ASK.search(q)),
    )


def _is_read_only_source_question(question: str) -> bool:
    return classify(question).read_only_source


__all__ = ["TurnIntent", "classify"]
