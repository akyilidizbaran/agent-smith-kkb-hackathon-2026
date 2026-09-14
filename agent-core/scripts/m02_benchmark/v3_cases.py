"""Golden set — demo gününe hazırlığın objektif ölçüsü.

Neden metin değil, DURUM üzerinden kontrol ediyoruz:
LLM'in ürettiği serbest metni "doğru mu?" diye kontrol etmek güvenilmez.
Bunun yerine agent'ın ürettiği ANALİZ TABLOSUNU denetliyoruz — satır sayısı,
kolonlar, bilinen gerçek değerler. Bunlar deterministiktir ve modelden
bağımsız olarak doğru/yanlış cevabı verir.

Beklenen değerler BDDK Aylık Bülten'den birebir doğrulanmıştır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd


@dataclass
class GoldenCase:
    id: str
    question: str
    why: str  # bu vaka neyi ölçüyor
    # Analiz tablosu üzerinde çalışan denetimler: (ad, kontrol fonksiyonu)
    table_checks: list[tuple[str, Callable[[pd.DataFrame], bool]]] = field(default_factory=list)
    # Nihai cevap metninde geçmesi/geçmemesi gerekenler
    answer_must_contain: list[str] = field(default_factory=list)
    answer_must_not_contain: list[str] = field(default_factory=list)
    # Doğru aracı seçti mi? Sonuç doğru olsa bile yanlış yoldan gelinmiş olabilir.
    must_use_tools: list[str] = field(default_factory=list)
    expect_no_table: bool = False
    max_steps_used: int = 8
    follow_up: str | None = None  # çok turlu senaryolar için


def _has_cols(*cols: str) -> Callable[[pd.DataFrame], bool]:
    return lambda df: all(any(c.lower() in col.lower() for col in df.columns) for c in cols)


def _has_time_column(df: pd.DataFrame) -> bool:
    """Bir zaman kolonu var mı — ADINDAN bağımsız.

    Kolon adı veri kaynağına göre değişiyor (`donem`, `observation_date`, …);
    golden set şemaya değil DAVRANIŞA bakmalı. Gerçek Lakehouse'a geçişte
    vakaların yeniden yazılmaması bu sayede.
    """
    if any(pd.api.types.is_datetime64_any_dtype(df[c]) for c in df.columns):
        return True
    return any(
        df[c].dropna().map(lambda v: hasattr(v, "year")).all() and not df[c].dropna().empty
        for c in df.columns
    )


def _rows(n: int) -> Callable[[pd.DataFrame], bool]:
    return lambda df: len(df) == n


def _value_near(expected: float, tol: float = 0.02) -> Callable[[pd.DataFrame], bool]:
    """Tabloda beklenen değere yakın bir sayı var mı?"""

    def check(df: pd.DataFrame) -> bool:
        for col in df.select_dtypes("number").columns:
            for v in df[col].dropna():
                if abs(float(v) - expected) <= abs(expected) * tol:
                    return True
        return False

    return check


CASES: list[GoldenCase] = [
    GoldenCase(
        id="G1_tek_deger",
        question="2025 Aralık ayında bankacılık sektöründe konut kredisi bakiyesi ne kadardı?",
        why="En temel akış: doğru kalemi bulup tek bir gerçek değeri getirebiliyor mu? "
        "BDDK'ya göre doğru cevap 678.970 milyon TL (TP 678.912 + YP 58).",
        table_checks=[("değer 678.970 milyon TL'ye yakın", _value_near(678_970))],
        answer_must_not_contain=["tahmin", "yaklaşık olarak bilinmiyor"],
        max_steps_used=6,
    ),
    GoldenCase(
        id="G2_aylik_seri",
        question="2025 yılında konut kredisi bakiyesini aylık olarak göster.",
        why="İlk ölçümde burada başarısız olundu: kalem adı tahmin edildi, sonra "
        "LIKE '%Konut%' ile üç ayrı kalem mükerrer toplandı. 12 ay = 12 satır olmalı.",
        table_checks=[
            ("tam 12 satır (mükerrer sayım yok)", _rows(12)),
            ("dönem kolonu var", _has_time_column),
        ],
        max_steps_used=8,
    ),
    GoldenCase(
        id="G3_turetilmis_hesap",
        question="2025 yılında konut kredisi bakiyesinin aylık değişimini hesapla.",
        why="Hesabın SQL'de yapılıp yapılmadığını ölçer. İlk ölçümde model kendi "
        "hesap yapıp 'aylık ortalama +1,5 milyon TL' gibi yanlış bir sonuç üretmişti.",
        table_checks=[
            ("değişim kolonu üretilmiş", lambda df: len(df.select_dtypes("number").columns) >= 2),
            ("12 satır", _rows(12)),
        ],
        max_steps_used=8,
    ),
    GoldenCase(
        id="G4_kapsam_disi",
        question="2015 yılında konut kredisi bakiyesi ne kadardı?",
        why="HALÜSİNASYON TESTİ. Veri 2021'de başlıyor. Agent sayı uydurmak yerine "
        "verinin kapsam dışı olduğunu söylemeli. Demoda en çok puan kaybettiren hata budur.",
        expect_no_table=True,
        answer_must_contain=["2021"],
        max_steps_used=6,
    ),
    GoldenCase(
        id="G5_karsilastirma",
        question="2025 yılında konut kredisi ile ihtiyaç kredisi bakiyelerini aylık olarak karşılaştır.",
        why="İki kalemi aynı tabloda hizalayabiliyor mu? Örnek senaryonun temel yapısı bu.",
        table_checks=[
            ("en az 12 satır", lambda df: len(df) >= 12),
            # İki kalem ya geniş formatta iki ölçüm sütunu, ya uzun formatta
            # iki katı satır olarak gelir. Eski "≥3 sütun" koşulu tek kalemde
            # de sağlanıyordu ve vakayı yanlışlıkla geçiriyordu.
            (
                "iki kalem gerçekten gelmiş",
                lambda df: len(df.select_dtypes("number").columns) >= 2 or len(df) >= 24,
            ),
        ],
        max_steps_used=8,
    ),
    GoldenCase(
        id="G7_tablo_uzerinde_hesap",
        question="2025 yılında konut kredisi bakiyesini aylık olarak göster.",
        follow_up="Tabloyu bozmadan, yeni bir sütun olarak aylık yüzde değişimi ekle.",
        why="Örnek senaryonun 2. sorusunun ('tabloyu bozmadan enflasyondan arındır') "
        "yapısal provası: mevcut sütundan türetilen hesap, tablo korunarak ekleniyor mu? "
        "Enflasyon serisi EVDS'den gelince aynı akış oraya uygulanacak.",
        table_checks=[("hâlâ 12 satır (tablo bozulmamış)", _rows(12))],
        must_use_tools=["workspace_compute_column"],
        max_steps_used=8,
    ),
    GoldenCase(
        id="G6_tabloyu_bozmadan",
        question="2025 yılında konut kredisi bakiyesini aylık olarak göster.",
        follow_up="Bu tabloyu hiç bozmadan, yeni bir sütun olarak taşıt kredisi bakiyesini ekle.",
        why="Örnek senaryonun 3. sorusunun birebir provası. Workspace'in yaşayıp "
        "yaşamadığını ölçer: ikinci soruda tablo yeniden kurulmamalı, SÜTUN eklenmeli.",
        # Eski "sütun sayısı >= 3" koşulu, tablo zaten 4 sütunlu olduğu için
        # sütun HİÇ eklenmese bile sağlanıyordu; vaka yanlışlıkla geçiyordu.
        # Doğru kanıt: sütunu ekleyen aracın gerçekten çalışmış olması.
        table_checks=[("hâlâ 12 satır (tablo bozulmamış)", _rows(12))],
        must_use_tools=["workspace_add_column"],
        max_steps_used=10,
    ),
]
