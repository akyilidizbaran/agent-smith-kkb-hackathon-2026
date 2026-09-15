"""Soru ön-koşulu (core/question_preflight): katalogda olmayan ölçüm/kırılım, ince frekans, tahmin yetkisi, öncül — LLM yok."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.catalog import ColumnRole, ColumnSpec, Coverage, DatasetSpec, Frequency, SemanticType  # noqa: E402
from kkb_agent.core.question_preflight import CatalogFacts, preflight  # noqa: E402


def _seed() -> CatalogFacts:
    spec = DatasetSpec(
        dataset_id="bddk_aylik_krediler", name="BDDK aylık krediler", description="Kalem bazında kredi bakiyeleri",
        source="bddk_monthly", frequency=Frequency.MONTHLY, time_column="donem", grain=["donem", "kalem"],
        coverage=Coverage(start=date(2023, 1, 1), end=date(2025, 12, 31)),
        columns=[
            ColumnSpec(name="kalem", role=ColumnRole.DIMENSION, dtype="VARCHAR", description="",
                       example_values=["Tüketici Kredileri - Konut", "Tüketici Kredileri - Taşıt"]),
            ColumnSpec(name="toplam", role=ColumnRole.MEASURE, dtype="DOUBLE", description="", semantic_type=SemanticType.STOCK,
                       unit="milyon TL", aliases=["kredi bakiyesi", "bakiye"]),
        ],
    )
    return CatalogFacts.from_specs([spec])


def test_temiz_soru_bayrak_yok() -> None:
    r = preflight("2025 Aralık konut kredisi bakiyesi ne kadar?", _seed(), tools={"lakehouse_query"})
    assert r.flags == () and r.note() == ""


def test_katalogda_olmayan_olcum_faiz() -> None:
    r = preflight("2025'te konut kredisi faiz oranı nasıl değişti?", _seed(), tools={"lakehouse_query"})
    assert any("katalogda olmayan ölçüm istendi: faiz" in f for f in r.flags)
    assert r.note().startswith("ÖN-KOŞUL")


def test_aktif_tablo_varken_katalog_kontrolu_yapilmaz() -> None:
    r = preflight("faiz oranı ortalaması", _seed(), tools=set(), has_table=True)
    assert not any("katalogda olmayan" in f for f in r.flags)


def test_il_kirilimi_ve_banka_grubu_yoksa_soylenir() -> None:
    r = preflight("İstanbul'daki konut kredisi bakiyesi 2025", _seed(), tools=set())
    assert any("'il' kırılımı istendi" in f for f in r.flags)
    r2 = preflight("katılım bankalarının konut kredisi bakiyesi", _seed(), tools=set())
    assert any("'banka_grubu' kırılımı istendi" in f for f in r2.flags)


def test_ince_frekans_ve_tahmin_yetkisi() -> None:
    r = preflight("konut kredisi bakiyesi haftalık nasıl?", _seed(), tools=set())
    assert any("weekly frekans istendi" in f for f in r.flags)
    r2 = preflight("2026 konut kredisi bakiyesi tahminin ne?", _seed(), tools={"lakehouse_query"})
    assert any("tahmin/öngörü istendi" in f for f in r2.flags)
    assert not any("tahmin" in f for f in preflight("2026 tahmin", _seed(), tools={"forecast"}).flags)


def test_puan_tutar_icin_tanimsiz_oran_icin_serbest() -> None:
    # UEB A08: "kaç puan arttı" bir bakiye için; oran/faiz sorusunda ("faiz kaç puan arttı") bayrak yok.
    r = preflight("2025 yılında konut kredisi bakiyesi kaç puan arttı?", _seed(), tools=set())
    assert any("'puan' (yüzde puanı) yalnız oran" in f for f in r.flags)
    assert not any("puan" in f for f in preflight("2025'te konut kredisi faizi kaç puan arttı?", _seed(), tools=set()).flags)
    assert not any("puan" in f for f in preflight("takip oranı kaç puan yükseldi?", _seed(), tools=set()).flags)


def test_oncul_kalibi_isaretlenir() -> None:
    r = preflight("2025'te konut kredileri düştüğü için taşıt kredileri arttı mı?", _seed(), tools=set())
    assert r.premise and any("öncül" in f for f in r.flags)
    r2 = preflight("2025'te taşıt kredisi neden arttı?", _seed(), tools=set())
    assert r2.premise
    assert not preflight("2025 taşıt kredisi bakiyesi", _seed(), tools=set()).premise
