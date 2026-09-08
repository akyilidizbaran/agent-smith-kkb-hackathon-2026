"""Semantic Catalog — agent'ın veriyi 'anlamasını' sağlayan katman.

Agent'ın doğru veri kaynağını seçebilmesi tamamen buraya bağlıdır. Ham şema
(tablo/kolon adları) bir LLM için yeterli değildir: bir sayının stok mu akım mı
olduğunu, hangi para biriminde ve hangi çarpanla tutulduğunu, kümülatif olup
olmadığını bilmeden doğru SQL üretilemez.

Bu modül veri ekibi ile agent ekibi arasındaki SÖZLEŞMEDİR. Lakehouse hangi
teknolojiyle kurulursa kurulsun, her veri seti kendini bu şemayla tanıtmalıdır.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class Frequency(str, Enum):
    """Serinin yayın frekansı. Frekans hizalamanın girdisidir."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    IRREGULAR = "irregular"


class SemanticType(str, Enum):
    """Ölçümün ekonomik doğası — frekans dönüşümünde hangi kuralın
    uygulanacağını belirler. Yanlış seçilirse aylık->çeyreklik gibi
    dönüşümler sessizce yanlış sonuç verir.

    STOCK : belirli bir andaki bakiye (ör. kredi stoku) -> dönem sonu değeri alınır
    FLOW  : dönem içi akım (ör. kullandırım, ciro)      -> toplanır
    RATE  : oran/faiz (ör. %)                            -> ağırlıklı ortalama
    INDEX : endeks (ör. TÜFE, konut fiyat endeksi)       -> dönem sonu ya da ortalama
    RATIO : paylar, yüzdeler (ör. NPL oranı)             -> yeniden hesaplanmalı
    COUNT : adet (ör. şube sayısı)                       -> stok gibi davranır
    """

    STOCK = "stock"
    FLOW = "flow"
    RATE = "rate"
    INDEX = "index"
    RATIO = "ratio"
    COUNT = "count"


class CumulativeKind(str, Enum):
    """BDDK slaytındaki uyarının kod karşılığı: 'bazı veriler paylaşım
    başlangıcından itibaren kümülatif giderken, bazıları yıllık bazda
    kümülatif gitmektedir.' İki farklı rejim var ve farklı ayrıştırma ister.

    NONE            : değer zaten o döneme ait
    YTD             : yıl başından itibaren birikimli -> yıl içinde fark alınır,
                      yılın ilk dönemi olduğu gibi kalır
    SINCE_INCEPTION : serinin başından itibaren birikimli -> düz fark alınır
    """

    NONE = "none"
    YTD = "ytd"
    SINCE_INCEPTION = "since_inception"


class ColumnRole(str, Enum):
    TIME = "time"           # dönem kolonu
    DIMENSION = "dimension"  # kırılım (il, banka grubu, para birimi...)
    MEASURE = "measure"      # sayısal ölçüm
    METADATA = "metadata"    # açıklama, kaynak notu vb.


class ColumnSpec(BaseModel):
    """Tek bir kolonun anlamsal tanımı."""

    name: str
    role: ColumnRole
    dtype: str = Field(description="DuckDB/SQL tipi: BIGINT, DOUBLE, DATE, VARCHAR...")
    description: str = Field(description="Türkçe, insan tarafından yazılmış açıklama")

    # --- Sadece MEASURE kolonları için ---
    semantic_type: SemanticType | None = None
    cumulative: CumulativeKind = CumulativeKind.NONE
    unit: str | None = Field(
        default=None, description="Ölçü birimi: 'TL', 'USD', 'yüzde', 'adet', 'endeks'"
    )
    unit_multiplier: float = Field(
        default=1.0,
        description="Ham değerin gerçek birime çevrilmesi için çarpan. "
        "BDDK bin TL yayınlıyorsa 1000.0 yazılır; agent her zaman gerçek birimle konuşur.",
    )

    # --- Doğal dil eşleşmesi ---
    aliases: list[str] = Field(
        default_factory=list,
        description="Kullanıcının bu kolonu çağırabileceği Türkçe ifadeler. "
        "Örn. konut_kredisi -> ['konut kredisi', 'mortgage', 'ev kredisi']. "
        "Agent'ın kolon seçimindeki isabet oranını en çok bu alan belirler.",
    )
    nullable: bool = True
    example_values: list[str] = Field(default_factory=list)


class Coverage(BaseModel):
    """Verinin gerçekte hangi aralığı kapsadığı. Agent bir soruyu
    cevaplamadan önce istenen dönemin kapsam içinde olup olmadığını
    kontrol etmeli; yoksa uydurmak yerine bunu söylemeli."""

    start: date
    end: date
    row_count: int | None = None
    known_gaps: list[str] = Field(
        default_factory=list, description="Eksik dönemler, ör. ['2023-02 (deprem)']"
    )


class DatasetSpec(BaseModel):
    """Lakehouse'daki tek bir analiz-hazır (Gold) tablonun tam tanımı."""

    dataset_id: str = Field(description="Benzersiz kimlik, ör. 'bddk_monthly_credits'")
    name: str = Field(description="İnsan okunur ad")
    description: str = Field(
        description="Bu tablo neyi anlatır, hangi soruları cevaplar. "
        "Agent'ın tablo seçimi büyük ölçüde bu metne dayanır."
    )

    source: str = Field(description="'BDDK' | 'TCMB-EVDS' | 'URL' | ...")
    source_url: str | None = None
    source_detail: str | None = Field(
        default=None, description="Kaynaktaki tam yer: tablo no, seri kodu, bülten adı"
    )

    frequency: Frequency
    time_column: str = Field(description="Dönem kolonunun adı")
    grain: list[str] = Field(
        description="Bir satırı benzersiz kılan kolonlar, ör. ['donem', 'il', 'banka_grubu']"
    )

    columns: list[ColumnSpec]
    coverage: Coverage

    tags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(
        default_factory=list,
        description="Analizi etkileyen uyarılar. Ör. 'Kaynak bin TL yayınlar, "
        "unit_multiplier ile gerçek TL'ye çevrilmiştir.'",
    )
    last_refreshed: date | None = None

    # ---- yardımcılar ----
    def measures(self) -> list[ColumnSpec]:
        return [c for c in self.columns if c.role == ColumnRole.MEASURE]

    def dimensions(self) -> list[ColumnSpec]:
        return [c for c in self.columns if c.role == ColumnRole.DIMENSION]

    def column(self, name: str) -> ColumnSpec | None:
        return next((c for c in self.columns if c.name == name), None)

    def to_prompt_card(self) -> str:
        """Kataloğu LLM'e verirken kullanılan kompakt gösterim.

        Context window kısıtı gerçek: 50 tabloluk bir kataloğun tamamını her
        turda prompt'a koyamayız. Bu yüzden önce arama ile daraltıp sadece
        ilgili tabloların kartını veriyoruz.
        """
        lines = [
            f"### {self.dataset_id} — {self.name}",
            f"Açıklama: {self.description}",
            f"Kaynak: {self.source}"
            + (f" ({self.source_detail})" if self.source_detail else ""),
            f"Frekans: {self.frequency.value} | Dönem kolonu: {self.time_column}",
            f"Kapsam: {self.coverage.start} → {self.coverage.end}"
            + (f" ({self.coverage.row_count} satır)" if self.coverage.row_count else ""),
            f"Grain: {', '.join(self.grain)}",
            "Kolonlar:",
        ]
        for c in self.columns:
            bits = [f"  - {c.name} ({c.dtype}, {c.role.value})"]
            if c.semantic_type:
                bits.append(f"[{c.semantic_type.value}]")
            if c.cumulative != CumulativeKind.NONE:
                bits.append(f"[KÜMÜLATİF: {c.cumulative.value}]")
            if c.unit:
                bits.append(f"birim={c.unit}")
            if c.unit_multiplier != 1.0:
                bits.append(f"x{c.unit_multiplier:g}")
            bits.append(f": {c.description}")
            if c.aliases:
                bits.append(f"(ayrıca: {', '.join(c.aliases)})")
            lines.append(" ".join(bits))
        for n in self.notes:
            lines.append(f"UYARI: {n}")
        return "\n".join(lines)
