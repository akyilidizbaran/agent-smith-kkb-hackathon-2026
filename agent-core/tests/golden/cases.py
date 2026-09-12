"""Golden set — demo gününe hazırlığın objektif ölçüsü.

Neden metin değil, DURUM üzerinden kontrol ediyoruz:
LLM'in ürettiği serbest metni "doğru mu?" diye kontrol etmek güvenilmez.
Bunun yerine agent'ın ürettiği ANALİZ TABLOSUNU denetliyoruz — satır sayısı,
kolonlar, bilinen gerçek değerler. Bunlar deterministiktir ve modelden
bağımsız olarak doğru/yanlış cevabı verir.

Beklenen değerler BDDK Aylık Bülten'den birebir doğrulanmıştır.
"""

from __future__ import annotations

import os
import pathlib

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
    # Araç yolu üzerinde denetim: (ad, adım listesi → bool). Birden çok meşru yol varsa
    # (ör. Gold: hazır tabloyu sorgulamak da fonksiyonu çağırmak da doğru) tek araç adı
    # dayatmak vakayı yanlışlıkla düşürür — ölçüldü, G9 0/3 böyle kaldı.
    tool_path_checks: list[tuple[str, Callable[[list], bool]]] = field(default_factory=list)
    expect_no_table: bool = False
    #: Araç adımı üst sınırı. Amacı kaçak döngüyü yakalamak, cimrilik değil.
    #:
    #: ADR-0027 (anlatı doğrulama) devreye girdikten sonra bütçeler bir kez yukarı
    #: çekildi ve sebebi ölçüldü: model tabloyu doğru üretip anlatıda tabloda olmayan
    #: bir sayı yazdığında guard cevabı geri gönderiyor, model de o sayıyı bu kez
    #: GERÇEKTEN hesaplıyor (`workspace_compute_column`). Yani fazladan adımlar
    #: kaçak değil, ONARIM — ve onarımsız hâli yanlış cevaptı:
    #:
    #:   G5, seed: "MISS:662.871, 2.078.450, 685.340, 2.160.923, 2,8, 3,1"
    #:   G6, seed: "MISS:155.515"
    #:
    #: Bütçeyi düşürmek bu vakaları "geçirir" ama uydurma sayıyı geri getirir.
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
        # 8 -> 11: grounding onarımı ölçüldü, 3 compute_column turu ekliyor (ADR-0027)
        max_steps_used=11,
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
        # 8 -> 11: aynı sebep; iki turlu vakada onarım ikinci turda da olabiliyor
        max_steps_used=11,
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
        # 10 -> 13: aynı sebep (ölçülen en kötü hâl 13)
        max_steps_used=13,
    ),
    GoldenCase(
        id="G8_ingest_ve_sorgu",
        question=(
            "Şu dosyayı veri havuzuna taslak seri olarak ekle ve ne yaptığını belgele: "
            + str(pathlib.Path(os.getenv("INGEST_ALLOWED_ROOT", "incoming")) / "konut_test.csv")
        ),
        follow_up="Şimdi eklediğin bu taslak seriyi aylık olarak tablo hâlinde göster.",
        why="Demo senaryosunun 2. sorusu: jüri yeni veri getirir, agent ingest eder VE belgeler, "
        "sonra o veriyle çalışır. İlk tur Architect'e açılan tek kapıyı (ingest_from_url) ölçer: "
        "eşleme veriden kanıtla önerildi mi, draft olarak yazıldı mı, kart run_id/SHA taşıyor mu. "
        "İkinci tur, ingest'ten sonra okuyucunun yeniden açılıp taslak seriyi gördüğünü ölçer "
        "(ölçülen açık: 'yeni: []'). Ön koşul: LAKEHOUSE_CORE_DIR ve INGEST_ALLOWED_ROOT ayarlı, "
        "dosya izinli kökte; aksi hâlde araç kayıtlı olmaz ve vaka 'araç hiç kullanılmadı' ile kalır.",
        table_checks=[("6 satır (dosyadaki altı ay)", _rows(6))],
        must_use_tools=["ingest_from_url", "lakehouse_query"],
        # İkinci turun cevabı tabloyu anlatır, seri kimliğini değil; ölçülen: model
        # "`konut_test` taslak serisi" yazdı, 'adhoc:' yazmadı. Kimlik kartta (1. tur) var;
        # cevapta aranan şey serinin TASLAK olduğunun söylenmesi.
        answer_must_contain=["taslak"],
        max_steps_used=12,
    ),
    GoldenCase(
        id="G9_gold_ceyreklik_ve_red",
        question="Konut kredisi bakiyesini 2025 yılı için çeyreklik olarak göster.",
        follow_up=(
            "Bu seriyi yıl başından itibaren birikimli kabul edip çeyreklik akımlara ayrıştır."
        ),
        why="Gold'un hayata dönüşü (ADR-0031). İlk tur: frekans dönüşümü SQL'de değil, katalog "
        "kurallı gold_align ile yapılmalı (stok → çeyreğin son ayı); 2025 = 4 çeyrek, Q4 = "
        "678.970 milyon TL (BDDK Aralık 2025). İkinci tur kullanıcının YANLIŞ öncülünü ölçer: "
        "seri birikimli değil, stok. Gold NOT_DECOMPOSABLE ile reddeder; agent fark alıp sayı "
        "üretmek yerine reddi ve sebebini söylemeli, ilk turun tablosu bozulmamalı. Ön koşul: "
        "LAKEHOUSE_CORE_DIR ayarlı (gold-run), gerçek veritabanı; aksi hâlde gold_* araçları "
        "kayıtlı olmaz ve vaka 'araç hiç kullanılmadı' ile kalır.",
        table_checks=[
            ("4 çeyrek (2025)", _rows(4)),
            ("dönem kolonu var", _has_time_column),
            ("2025 Q4 = 678.970 milyon TL", _value_near(678_970)),
        ],
        must_use_tools=["gold_decompose"],
        # İlk tur için iki meşru yol var ve ikisi de Gold'dur: gold_align çağrısı ya da
        # `python -m lakehouse gold` ile kurulmuş gold.* tablosunu SQL ile sorgulamak.
        # Ölçüldü: model hazır tabloyu buldu (arama → describe → query), 4 satır doğru;
        # yalnız gold_align'ı şart koşan ilk sürüm 0/3 kalmıştı.
        tool_path_checks=[
            (
                "çeyreklik değerler Gold'dan geldi (gold_align ya da gold.* tablosu), SQL ile toplanmadı",
                lambda steps: any(s.tool_name == "gold_align" and s.ok for s in steps)
                or any(
                    s.tool_name == "lakehouse_query" and s.ok
                    and "from gold." in str(s.tool_args.get("sql", "")).lower()
                    for s in steps
                ),
            ),
        ],
        # Reddin cevaba yansıması: kullanıcı 'birikimli' dedi, cevap bunu düzeltmeli.
        answer_must_contain=["birikimli"],
        max_steps_used=10,
    ),
]
