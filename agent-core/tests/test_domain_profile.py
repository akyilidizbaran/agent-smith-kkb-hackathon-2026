"""Jeneriklik testleri.

Şartname platformun "içi boşaltılıp bambaşka bir sağlık verisiyle de
çalışabilir" olmasını istiyor. Bu dosya o iddiayı KANITA çevirir: aynı motor,
tamamen farklı bir alanın kataloğuyla kurulduğunda modele giden metinlerin de
o alana uyduğunu doğrular.

Ayrıca bir regresyon koruması: kod tabanına yeniden finansa özel örnek
sızarsa `test_modele_giden_metinlerde_alan_terimi_yok` bunu yakalar.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.catalog import (  # noqa: E402
    ColumnRole,
    ColumnSpec,
    Coverage,
    DatasetSpec,
    Frequency,
    SemanticType,
)
from kkb_agent.core.agent import SYSTEM_PROMPT  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.domain import DomainProfile  # noqa: E402
from kkb_agent.tools.lakehouse import (  # noqa: E402
    LakehouseDescribeTool,
    LakehouseDistinctValuesTool,
    LakehouseQueryTool,
    LakehouseSearchTool,
)
from kkb_agent.tools.workspace import (  # noqa: E402
    WorkspaceAddColumnTool,
    WorkspaceComputeColumnTool,
    WorkspaceShowTool,
)

# Finans alanına ait, motorda görünmemesi gereken terimler.
FINANS_TERIMLERI = [
    "konut", "kredi", "bddk", "evds", "tüfe", "tufe",
    "enflasyon", "banka", "faiz", "mortgage", "taşıt", "tasit",
]

SAGLIK_KATALOGU = DatasetSpec(
    dataset_id="hastane_basvurulari",
    name="Hastane Başvuruları",
    description="İl ve branş kırılımında aylık hastane başvuru sayıları.",
    source="Sağlık Bakanlığı",
    frequency=Frequency.MONTHLY,
    time_column="ay",
    grain=["ay", "il", "brans"],
    columns=[
        ColumnSpec(name="ay", role=ColumnRole.TIME, dtype="DATE", description="Başvuru ayı"),
        ColumnSpec(
            name="brans", role=ColumnRole.DIMENSION, dtype="VARCHAR",
            description="Tıbbi branş",
            example_values=["Kardiyoloji", "Ortopedi"],
        ),
        ColumnSpec(name="il", role=ColumnRole.DIMENSION, dtype="VARCHAR", description="İl"),
        ColumnSpec(
            name="basvuru_sayisi", role=ColumnRole.MEASURE, dtype="BIGINT",
            description="Başvuru adedi", semantic_type=SemanticType.COUNT, unit="adet",
        ),
    ],
    coverage=Coverage(start=date(2021, 1, 1), end=date(2026, 6, 1)),
    tags=["sağlık", "başvuru"],
)


class _StubLakehouse:
    def list_datasets(self): return [SAGLIK_KATALOGU]
    def get_dataset(self, dataset_id): return SAGLIK_KATALOGU
    def search_datasets(self, query, limit=5): return [SAGLIK_KATALOGU]
    def execute_sql(self, sql, *, max_rows=10_000): raise NotImplementedError
    def preview(self, dataset_id, n=5): raise NotImplementedError
    def health(self): return {"ok": True}


def _tum_arac_metinleri(profile: DomainProfile) -> str:
    """Modele giden bütün araç metinlerini tek bir dize olarak toplar."""
    lake, ws = _StubLakehouse(), None
    from kkb_agent.core.workspace import AnalysisWorkspace
    ws = AnalysisWorkspace()
    registry = ToolRegistry(profile)
    registry.register_all([
        LakehouseSearchTool(lake),
        LakehouseDescribeTool(lake),
        LakehouseDistinctValuesTool(lake),
        LakehouseQueryTool(lake, ws),
        WorkspaceAddColumnTool(lake, ws),
        WorkspaceComputeColumnTool(ws),
        WorkspaceShowTool(ws),
    ])
    import json
    return json.dumps(registry.schemas(), ensure_ascii=False) + registry.describe()


def test_modele_giden_metinlerde_alan_terimi_yok() -> None:
    """Nötr profille kurulan motorda hiçbir finans terimi geçmemeli.

    Regresyon koruması: araç açıklamalarına yeniden alan örneği sızarsa burada
    yakalanır. Bu metinler her turda prompt'a giriyor.
    """
    metin = (_tum_arac_metinleri(DomainProfile.generic()) + SYSTEM_PROMPT).lower()
    sizanlar = [term for term in FINANS_TERIMLERI if term in metin]
    assert not sizanlar, f"modele giden metinlere alan terimi sızmış: {sizanlar}"


def test_saglik_katalogundan_profil_turer() -> None:
    """Katalog değişince profil kendiliğinden ona uyar — model tahmini yok."""
    p = DomainProfile.from_catalog([SAGLIK_KATALOGU])
    assert p.domain == "Sağlık Bakanlığı kaynaklı veriler"
    assert p.example_table == "hastane_basvurulari"
    assert p.example_time_column == "ay"
    assert p.example_category_column == "brans"
    assert p.example_measure == "basvuru_sayisi"
    assert p.example_entity == "Kardiyoloji"


def test_ornek_varlik_kisa_arama_terimi_olur() -> None:
    """Kanonik tam ad değil, kullanıcının yazacağı kısa terim üretilmeli.

    Ölçülmüş sebep: tam ad ("Tüketici Kredileri - Konut") örnek olarak
    verildiğinde model bunu `contains` filtresine birebir yazdı ve golden set
    5/7'den 1/7'ye düştü. Örneğin gerçek olması yetmez, iyi olması gerekir.
    """
    from kkb_agent.domain import _kisa_terim

    assert _kisa_terim("Tüketici Kredileri - Konut") == "Konut"
    assert _kisa_terim("Tüketici Kredileri - Konut (Dövize Endeksli)") == "Konut"
    assert _kisa_terim("Kardiyoloji") == "Kardiyoloji"
    assert _kisa_terim("Bireysel Kredi Kartları") == "Bireysel Kredi Kartları"
    # Ayırıcı yoksa ve uzunsa kırpılır ama boş kalmaz
    assert _kisa_terim("x" * 60)


def test_ornekler_makul_uzunlukta() -> None:
    """Profilden gelen her örnek, bir istem içinde örnek olarak durabilmeli."""
    p = DomainProfile.from_catalog([SAGLIK_KATALOGU])
    for alan in ("example_entity", "example_table", "example_measure",
                 "example_time_column", "example_category_column"):
        deger = getattr(p, alan)
        assert deger and len(deger) <= 40, f"{alan} örnek olarak fazla uzun: {deger!r}"


def test_arac_semalari_yeni_alana_uyar() -> None:
    """Sağlık kataloğuyla kurulan motorun araç örnekleri de sağlık alanından olur.

    Not: tablo adı artık şemalarda örnek olarak geçmiyor — workspace_add_column
    yapılandırılmış parametrelere geçtiğinden tabloyu model katalogdan seçiyor.
    """
    p = DomainProfile.from_catalog([SAGLIK_KATALOGU])
    metin = _tum_arac_metinleri(p)
    assert "basvuru_sayisi" in metin, "ölçüm örneği alana uymalı"
    assert "Kardiyoloji" in metin, "varlık örneği alana uymalı"
    assert "brans" in metin, "kırılım örneği alana uymalı"
    assert not any(t in metin.lower() for t in FINANS_TERIMLERI)


def test_system_prompt_alana_gore_doldurulur() -> None:
    p = DomainProfile.from_catalog([SAGLIK_KATALOGU], audience="sağlık yöneticisi")
    rendered = p.render(SYSTEM_PROMPT)
    assert "Sağlık Bakanlığı kaynaklı veriler" in rendered
    assert "sağlık yöneticisi" in rendered
    assert "{domain}" not in rendered and "{audience}" not in rendered


def test_bos_katalog_notr_profil_verir() -> None:
    """Veri yokken motor yine de kurulabilmeli."""
    p = DomainProfile.from_catalog([])
    assert p.domain == "yapılandırılmış veri"
    assert "{" not in p.render(SYSTEM_PROMPT).replace("{example", "")


def test_taninmayan_yer_tutucu_bozulmaz() -> None:
    """SQL örneklerindeki süslü parantezler render'dan zarar görmemeli."""
    p = DomainProfile.generic()
    assert p.render("SELECT {bilinmeyen} FROM x") == "SELECT {bilinmeyen} FROM x"
    assert p.render("{example_table}") == "bir_tablo"
