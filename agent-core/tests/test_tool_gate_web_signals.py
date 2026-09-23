"""Araç kapısı — dış-kaynak/link/pdf sinyalleri web ailesini açar (URL'siz başlık metni, dış kaynak adı, link/pdf ekleri).

Gözlenen hata: UI bağlantıyı yalnız başlık metni olarak aktarınca (URL gömülü değil) `_WEB` hiçbir
sinyale uymuyordu; web araçları modele sunulmuyor, ajan yerel katalog döngüsünde tıkanıyordu.
Bu düzeltme routing katmanındadır: kapı yalnız sunulan şemayı genişletir, yürütme yetkisini değil.

Dış-kaynak tanıma CONFIG-DRIVEN'dır: kaynak adları çekirdek koda gömülü değil, `source_hints.json`
→ `financial_sources` yapısından okunur. Bu testler temsilî istemlerle kapıyı sınar; çekirdeğin kaynak adına özel olmadığını (yapılandırılmamış ad web açmaz) da doğrular.
"""
from __future__ import annotations

from kkb_agent.core import tool_gate
from kkb_agent.core.web_routing import matched_external_source

_REGISTERED = frozenset(tool_gate.ALWAYS) | tool_gate.WEB | tool_gate.ARCHITECT | tool_gate.CHART

# Dış kaynak — bağlantı yalnız başlık metni olarak; URL gömülü DEĞİL.
TEFAS_TITLE = (
    "Fon piyasası tarafını da görelim: TEFAS istatistik raporundaki aylık işlem hacmini ve takas "
    "tutarını al, elimizdeki aylık tabloya ay bazında ekle ve havuza kaydet.\n\n"
    "TEFAS | İstatistikler"
)
# Sektör raporu PDF — "linkinden ... pdfindeki"; URL gömülü DEĞİL.
ODMD_TITLE = (
    "Otomotiv satışlarını birlik sitesindeki pazar raporları linkinden "
    '"2026 Temmuz Pazar Değerlendirme" pdfindeki tablolarla karşılaştır.'
)


def _web_open(question: str) -> bool:
    return bool(tool_gate.WEB & tool_gate.decide(question, _REGISTERED).allowed)


def test_tefas_title_only_prompt_opens_web_family():
    assert _web_open(TEFAS_TITLE)


def test_odmd_pdf_title_only_prompt_opens_web_family():
    assert _web_open(ODMD_TITLE)


def test_embedded_url_still_opens_web_family():
    assert _web_open(TEFAS_TITLE + "\nhttps://www.tefas.gov.tr/")
    assert _web_open(ODMD_TITLE + "\nhttps://www.odmd.org.tr/web_2837_1/neuralnetwork.aspx?type=35")


def test_local_only_questions_keep_web_family_closed():
    # Yerel havuzdan karşılanan sorular web ailesini AÇMAMALI (aksi halde gereksiz araç + yanıltıcı yönelim).
    for question in (
        "Konut kredisi faiz oranını 2025 için aylık ortalama olarak göster.",
        "2024 ve 2025 için aylık dolar kuru ile politika faizini yan yana göster.",
        "BDDK aylık bülten mevduat verisini getir.",
        "elimizde hangi veriler var",
        "TÜFE genel endeksini 2025 için getir.",
    ):
        assert not _web_open(question), question


def test_external_source_recognition_is_config_driven():
    # Eşleşme source_hints.financial_sources'tan gelir (kaynak adı çekirdekte değil).
    assert (matched_external_source(TEFAS_TITLE) or {}).get("key") == "tefas"
    assert (matched_external_source(ODMD_TITLE) or {}).get("key") == "odmd"
    # Yapılandırmada OLMAYAN kaynak, config eşleşmesi ÜRETMEZ (host-pin buna dayanır). Web'in tümden
    # kapanması BEKLENTİSİ YOK: açık URL ya da genel dış-kaynak sözdizimi ayrı yollarla web açabilir (P1).
    assert matched_external_source("Bloomberg terminalinden veriyi getir") is None
