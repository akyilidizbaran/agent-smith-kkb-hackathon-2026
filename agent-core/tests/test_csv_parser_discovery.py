"""Generic CSV başlık/preamble keşfi ve sağlam ayraç seçimi (kaynak-bağımsız).

Gerçek dış-kaynak dışa aktarımları (TEFAS gibi) çoğu zaman başlarında metadata/preamble satırları ve
sonlarında bir 'Toplam' özet satırı taşır; ayraç TR Excel'inde ';' olur (',' ondalıktır). Önceki
`sep=None` sniff'i preamble'da çöküyor (ParserError) veya ',' ayracıyla sayıları bölüyordu. Bu testler
kaynak adına özel değildir; keşfin davranışını doğrular. Sayıya çevirme aşağı yönlü (profile) katmandadır.
"""
from __future__ import annotations

from kkb_agent.builder.read import _table_from_bytes


def test_semicolon_turkish_numbers_split_cleanly():
    csv = (
        "Dönem;Toplam İşlem Hacmi (TL);Net Takas Tutarı (TL)\n"
        "2021-01;1.234.567.890.123,45;234.567.890.123,40\n"
        "2024-11;12.345.678.901,20;2.345.678.901,30\n"
    ).encode()
    df = _table_from_bytes(csv, "x.csv")
    assert list(df.columns) == ["Dönem", "Toplam İşlem Hacmi (TL)", "Net Takas Tutarı (TL)"]
    assert df.shape == (2, 3)
    # Hücreler ham string kalır (sayı çevirimi profile katmanında); binlik/ondalık BÖLÜNMEZ.
    assert df.iloc[1, 1] == "12.345.678.901,20"


def test_preamble_rows_are_skipped_not_crashing():
    csv = (
        "TEFAS - Toplam İşlem Hacmi Raporu\n"
        "Para Birimi: TL\n"
        "Başlangıç: 2022-05 Bitiş: 2024-11\n"
        "\n"
        "Dönem;Toplam İşlem Hacmi (TL);Net Takas Tutarı (TL)\n"
        "2024-11;12.345.678.901,20;2.345.678.901,30\n"
        "2023-03;98.765.432.109,80;19.876.543.210,90\n"
    ).encode()
    df = _table_from_bytes(csv, "x.csv")
    assert list(df.columns) == ["Dönem", "Toplam İşlem Hacmi (TL)", "Net Takas Tutarı (TL)"]
    assert df.shape == (2, 3)  # preamble atıldı, iki veri satırı kaldı


def test_tab_delimited_with_preamble():
    tsv = "Rapor başlığı\nAy\tHacim\tTakas\n2025-12\t12345\t2345\n".encode()
    df = _table_from_bytes(tsv, "x.tsv")
    assert list(df.columns) == ["Ay", "Hacim", "Takas"]
    assert df.shape == (1, 3)


def test_plain_header_first_row_still_works():
    # Preamble yokken ilk satır (metin) başlık, altı veri — regresyon koruması.
    csv = "Tarih;Deger\n2025-01;10\n2025-02;20\n".encode()
    df = _table_from_bytes(csv, "x.csv")
    assert list(df.columns) == ["Tarih", "Deger"]
    assert df.shape == (2, 2)


def test_tefas_style_export_comma_quoted_turkish_decimals_with_preamble():
    # TEFAS biçimli dışa aktarım (değerler sentetik): virgül ayraç + TIRNAKLI Türkçe ondalık virgül + metadata preamble + Toplam satırı.
    real = (
        "Dışa Aktarım Tarihi:,23.09.2026 11:12:23\n"
        "Toplam Kayıt Sayısı:,3\n"
        "Dönem,Toplam İşlem Hacmi (TL),Günlük Ortalama İşlem Hacmi (TL),Net Takas Tutarı (TL)\n"
        '2021-01,"12345678901,20","617283945,06","2345678901,30"\n'
        '2023-03,"98.765.432.109,80","5.000.000.000,00","19.876.543.210,90"\n'
        '2024-11,"1234567890123,45","53676864788,12","234567890123,40"\n'
        'Toplam,"1.345.679.001.134,45","65.900.000.000,00","256.790.112.235,60"\n'
    ).encode()
    df = _table_from_bytes(real, "tefas.csv")
    # 1) metadata başlık sanılmadı; gerçek başlık bulundu.
    assert list(df.columns) == [
        "Dönem", "Toplam İşlem Hacmi (TL)", "Günlük Ortalama İşlem Hacmi (TL)", "Net Takas Tutarı (TL)"
    ]
    # 2) tırnaklı TR ondalık virgüller BÖLÜNMEDİ; hücreler ham string.
    row = df[df["Dönem"] == "2021-01"].iloc[0]
    assert row["Toplam İşlem Hacmi (TL)"] == "12345678901,20"
    assert row["Net Takas Tutarı (TL)"] == "2345678901,30"
    # 3) gerçek veri satırları korundu (Dönem + Toplam dahil ham okundu; Toplam temizliği semantik katmanda).
    assert set(df["Dönem"]) >= {"2024-11", "2023-03", "2021-01"}
    # 6) kontrol değerleri (exact) — tüm üç dönem:
    for donem, hacim, takas in [
        ("2021-01", "12345678901,20", "2345678901,30"),
        ("2023-03", "98.765.432.109,80", "19.876.543.210,90"),
        ("2024-11", "1234567890123,45", "234567890123,40"),
    ]:
        r = df[df["Dönem"] == donem].iloc[0]
        assert r["Toplam İşlem Hacmi (TL)"] == hacim, donem
        assert r["Net Takas Tutarı (TL)"] == takas, donem


def test_toplam_summary_row_is_excluded_from_monthly_join():
    # 3) 'Toplam' özet satırı aylık gözlem sayılmaz: geçerli ay anahtarı üretmez → join'e girmez.
    import pandas as pd
    from kkb_agent.tools.web import monthly_enrich_join
    left = pd.DataFrame({"Tarih": ["2024-11-01", "2023-03-01"], "TP": [1, 2]})
    right = pd.DataFrame({"Dönem": ["2024-11", "2023-03", "Toplam"],
                          "Hacim": ["12.345", "98.765", "111.110"]})
    merged, err = monthly_enrich_join(left, right)
    assert err is None and len(merged) == 2                       # Toplam satırı taban satır eklemedi
    assert merged.loc[merged["Tarih"] == "2024-11-01", "Hacim"].iloc[0] == "12.345"
