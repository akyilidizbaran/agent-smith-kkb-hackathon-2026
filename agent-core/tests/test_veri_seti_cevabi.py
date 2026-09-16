"""'Elimizde hangi veriler var' cevabı: konu başlıkları ve yeni kaynağın okunur adı (15 Eyl kullanıcı kararı, ADR-0082 eki).

İçerik her soruda canlı katalogdan okunur. İki sınır kapatıldı: cevap yalnız kaynak/sayı/dönem veriyordu (konu yoktu) ve
source_hints.json'da adı olmayan yeni kaynak ham kimlikle ("tuik: 5 seri") görünüyordu.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.catalog import ColumnRole, ColumnSpec, Coverage, DatasetSpec, Frequency, SemanticType  # noqa: E402
from kkb_agent.core.small_talk import data_sets_reply  # noqa: E402
from kkb_agent.domain import DomainProfile  # noqa: E402
from kkb_agent.labels import readable_source, source_display_name, topic_of, topics_summary  # noqa: E402
from kkb_agent.source_hints import load_source_hints  # noqa: E402


def _spec(sid: str, source: str, name: str, aliases: list[str], tags: list[str] | None = None, url: str | None = None,
          start: date = date(2016, 1, 31), end: date = date(2026, 6, 30)) -> DatasetSpec:
    return DatasetSpec(dataset_id=sid, name=name, description="d", source=source, source_url=url, frequency=Frequency.MONTHLY,
                       time_column="observation_date", grain=["observation_date"], coverage=Coverage(start=start, end=end, row_count=1),
                       tags=tags or [],
                       columns=[ColumnSpec(name="observation_date", role=ColumnRole.TIME, dtype="DATE", description="dönem"),
                                ColumnSpec(name="value", role=ColumnRole.MEASURE, dtype="DOUBLE", description="değer",
                                           semantic_type=SemanticType.STOCK, unit="TL", aliases=aliases)])


def _finturk() -> list[DatasetSpec]:   # gerçek katalogdaki biçim: "<ölçüm>, <İL> (Bireysel Bankacılık, Sektör)"
    out = []
    for il, il_alias in (("ADANA", "adana"), ("İSTANBUL", "istanbul"), ("VAN", "van")):
        for measure, alias in (("Konut Kredisi", "konut kredisi"), ("Taşıt Kredisi", "taşıt kredisi"), ("Bireysel Kredi Kartları", "kredi kartı")):
            out.append(_spec(f"bddk_finturk:{il}_{measure}", "bddk_finturk", f"{measure}, {il} (Bireysel Bankacılık, Sektör)",
                             [f"{il_alias} {alias}", f"{il_alias} ili {alias}"], tags=["kredi", "il", "bddk"], start=date(2016, 3, 31)))
    return out


def test_il_bazli_kaynak_il_x_konu_ozetlenir_il_adi_konuya_girmez() -> None:
    assert topic_of(_finturk()[3]) == ("konut kredisi", "İSTANBUL"), "İ/i ve aksan farkına rağmen il adı atılır"
    assert topics_summary(_finturk()) == "3 il × 3 konu: konut kredisi, taşıt kredisi, kredi kartı", "3 harfli il (VAN) da varlık"


def test_kisaltma_serinin_adindaki_yazimla_ve_konu_siniri() -> None:
    evds = [_spec("evds:TP.FG.J0", "evds", "Tüketici Fiyat Endeksi (TÜFE, genel)", ["tüfe", "enflasyon"]),
            _spec("evds:TP.HPBITABLO1.18", "evds", "Para Arzı M3 (bin TL)", ["m3", "geniş para arzı"]),
            _spec("evds:TP.BISPOLFAIZ.TUR", "evds", "TCMB Politika Faiz Oranı (%)", ["politika faizi"]),
            _spec("evds:TP.TUKFIY2025.GENEL", "evds", "Tüketici Fiyat Endeksi (TÜFE, genel, 2025=100)", ["tüfe"])]
    assert topics_summary(evds) == "konular: TÜFE, M3, politika faizi", "aynı konu (iki TÜFE) bir kez"
    many = [_spec(f"x:{i}", "x", f"Seri {i}", [f"konu {i}"]) for i in range(9)]
    assert topics_summary(many) == "konular: konu 0, konu 1, konu 2, konu 3, konu 4, konu 5 ve 3 konu daha"
    assert topics_summary([_spec("x:1", "x", "Krediler, Toplam (Sektör, Bilanço)", [])]) == "konu: Krediler", "takma ad yoksa ad sadeleşir"


def test_yeni_kaynak_ayar_dosyasi_olmadan_okunur_adla() -> None:
    tuik = [_spec("tuik:ISG01", "tuik", "İşgücüne Katılma Oranı (%)", ["işgücüne katılma"], url="https://data.tuik.gov.tr/Bulten/Index?p=1")]
    assert source_display_name("tuik", tuik) == "TÜİK", "kurum adı adresten (tuik.gov.tr) eşleşir"
    assert source_display_name("tuik") == "TÜİK", "adres yoksa kimlikten"
    other = [_spec("acme:1", "acme", "Satış", ["satış"], url="https://veri.acme-istatistik.com/tablo/1")]
    assert source_display_name("acme", other) == "veri.acme-istatistik.com", "kurum yoksa alan adı"
    assert source_display_name("bilinmeyen") == "bilinmeyen" and source_display_name("bddk_monthly") == "BDDK Aylık Bülten"
    assert readable_source("tuik — İşgücüne Katılma Oranı") == "TÜİK — İşgücüne Katılma Oranı"
    assert DomainProfile.from_catalog(tuik).domain == "TÜİK kaynaklı veriler"


def test_cevap_kaynak_basina_satir_sayi_donem_ve_konu_tasir() -> None:
    specs = [*_finturk(),
             _spec("bddk_monthly:1534_Toplam", "bddk_monthly", "Tüketici Kredileri - Konut, Toplam (Sektör)", ["konut kredisi"]),
             _spec("evds:TP.FG.J0", "evds", "Tüketici Fiyat Endeksi (TÜFE, genel)", ["tüfe"], end=date(2026, 7, 3)),
             _spec("tuik:ISG01", "tuik", "İşgücüne Katılma Oranı (%)", ["işgücüne katılma"], url="https://data.tuik.gov.tr/x"),
             _spec("adhoc:acil", "adhoc", "acil_basvuru — acil.csv (taslak)", [], start=date(2025, 1, 31), end=date(2025, 12, 31))]
    reply = data_sets_reply(specs, load_source_hints())
    lines = reply.splitlines()
    assert lines[0] == "Veri havuzunda şu kaynaklardan yüklü seriler var:"
    assert "- BDDK FinTürk (il bazında): 9 seri (2016-03 → 2026-06); 3 il × 3 konu: konut kredisi, taşıt kredisi, kredi kartı" in lines
    assert "- BDDK Aylık Bülten: 1 seri (2016-01 → 2026-06); konu: konut kredisi" in lines
    assert "- TCMB EVDS: 1 seri (2016-01 → 2026-07); konu: TÜFE" in lines
    assert "- TÜİK: 1 seri (2016-01 → 2026-06); konu: işgücüne katılma" in lines, "yeni kaynak ham kimlikle ('tuik:') görünmez"
    assert lines[-1] == "Kullanıcının eklediği seriler: acil basvuru (2025-01 → 2025-12)."
    assert "tuik:" not in reply and "bddk_" not in reply
