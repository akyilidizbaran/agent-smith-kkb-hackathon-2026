"""Web yönlendirme planı: ağ/LLM yok; allowlist ve kullanıcı kapsamı saf fonksiyonlarda sınanır."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.web_routing import (
    addresses,
    discovery_requested,
    general_public_fallback_plan,
    host_of,
    public_db_fallback,
    public_fallback_plan,
    source_domains,
    web_forbidden,
    web_requested,
    within_domains,
)
from kkb_agent.source_hints import clear_cache, load_source_hints


@pytest.fixture(autouse=True)
def clear_source_hint_cache():
    clear_cache()
    yield
    clear_cache()


def test_explicit_url_and_bare_domain_are_normalized_without_accepting_lookalikes():
    assert addresses("https://www.bddk.gov.tr/bulten?yil=2024, lütfen oku") == [
        "https://www.bddk.gov.tr/bulten?yil=2024"
    ]
    assert host_of("https://www.bddk.gov.tr/bulten") == "bddk.gov.tr"
    assert within_domains("https://data.bddk.gov.tr/file.csv", ["bddk.gov.tr"])
    assert within_domains("https://bddk.gov.tr.evil.example/file.csv", ["bddk.gov.tr"]) is False


def test_bare_file_names_are_not_misread_as_web_domains():
    assert addresses("Bu dosyayı analiz et: weather.csv") == []
    assert addresses("https://data.example.org/weather.csv") == ["https://data.example.org/weather.csv"]


@pytest.mark.parametrize(
    "question",
    [
        "İnternette arama yapma, yalnızca veritabanını kullan.",
        "Web araması yapma.",
        "İnterneti kullanma.",
    ],
)
def test_web_yasagi_olumlu_web_kelimesi_gecse_de_onceliklidir(question):
    assert web_forbidden(question)
    assert web_requested(question) is False


def test_positive_search_is_not_misclassified_as_web_prohibition():
    question = "Web araması yap ve resmi kaynağı bul."
    assert web_forbidden(question) is False
    assert web_requested(question)


def test_source_pin_and_discovery_domains_come_from_configuration():
    assert source_domains("BDDK'dan 2024 verisini getir") == ["bddk.gov.tr", "bddk.org.tr"]
    assert source_domains("https://www.bddk.org.tr/bulten") == ["bddk.org.tr"]
    assert discovery_requested("BDDK sitesinden son bülteni bul")
    assert discovery_requested("https://www.bddk.org.tr")
    assert not discovery_requested("https://www.bddk.org.tr/bulten")


def test_only_catalogued_public_sources_can_enable_fallback():
    assert public_db_fallback("2024 verisini ara", ["bddk_monthly"])
    assert not public_db_fallback("2024 verisini ara", ["adhoc"])
    assert not public_db_fallback("müşteri hesap numarası verisini ara", ["bddk_monthly"])
    assert not public_db_fallback("veritabanını kullan, web araması yapma", ["bddk_monthly"])
    assert not public_db_fallback("2024 verisini ara", [])


def test_fallback_query_uses_catalog_names_and_years_not_raw_question_or_sql():
    catalog = {
        "loans": SimpleNamespace(name="BDDK İhtiyaç Kredileri", source="bddk_monthly"),
        "cards": SimpleNamespace(name="Bireysel Kredi Kartları", source="bddk_monthly"),
    }
    provenance = SimpleNamespace(dataset_ids=["loans", "cards"])
    lakehouse = SimpleNamespace(get_dataset=catalog.__getitem__)
    question = "2022-2024 dönemini bul; SQL: DROP TABLE customers"

    plan = public_fallback_plan(question, provenance, lakehouse)

    assert plan == {
        "query": "BDDK İhtiyaç Kredileri Bireysel Kredi Kartları 2022 2024",
        "include_domains": ["bddk.gov.tr", "bddk.org.tr"],
        "topic": "finance",
        "max_results": 5,
    }
    assert "DROP" not in plan["query"] and "customers" not in plan["query"]


def test_user_source_pin_intersects_with_catalog_allowlist():
    provenance = SimpleNamespace(dataset_ids=["loans"])
    lakehouse = SimpleNamespace(
        get_dataset=lambda _dataset_id: SimpleNamespace(name="BDDK Aylık Bülten", source="bddk_monthly")
    )

    plan = public_fallback_plan("https://www.bddk.org.tr bültenini ara", provenance, lakehouse)

    assert plan is not None
    assert plan["include_domains"] == ["bddk.org.tr"]


def test_explicit_public_source_can_build_a_bounded_plan_after_no_catalog_match():
    lakehouse = SimpleNamespace(get_dataset=lambda _id: None)

    plan = public_fallback_plan(
        "BDDK'dan 2024 kredi verisini getir",
        None,
        lakehouse,
        search_terms="2024 kredi verileri",
    )

    assert plan is not None
    assert plan["include_domains"] == ["bddk.gov.tr", "bddk.org.tr"]
    assert plan["query"] == "BDDK kredi 2024"


def test_no_catalog_match_requires_explicit_configured_public_source_and_safe_terms():
    lakehouse = SimpleNamespace(get_dataset=lambda _id: None)
    assert public_fallback_plan(
        "2024 kredi verilerini getir", None, lakehouse, search_terms="2024 kredi verileri"
    ) is None
    assert public_fallback_plan(
        "BDDK'dan 2024 kredi verisini getir", None, lakehouse, search_terms="SELECT * FROM customers"
    ) is None
    assert public_fallback_plan(
        "BDDK'dan 2024 müşteri hesap numaralarını getir", None, lakehouse, search_terms="müşteri hesap"
    ) is None


@pytest.mark.parametrize(
    ("provenance", "lakehouse"),
    [
        (SimpleNamespace(dataset_ids=[]), SimpleNamespace(get_dataset=lambda _id: None)),
        (SimpleNamespace(dataset_ids=["unknown"]), SimpleNamespace(get_dataset=lambda _id: (_ for _ in ()).throw(KeyError()))),
        (SimpleNamespace(dataset_ids=["private"]), SimpleNamespace(
            get_dataset=lambda _id: SimpleNamespace(name="Private data", source="internal")
        )),
    ],
)
def test_missing_or_non_public_catalog_metadata_fails_closed(provenance, lakehouse):
    assert public_fallback_plan("2024 verisini bul", provenance, lakehouse) is None


def test_empty_source_hints_configuration_remains_valid(tmp_path, monkeypatch):
    empty_hints = tmp_path / "empty-source-hints.json"
    empty_hints.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setenv("SOURCE_HINTS_FILE", str(empty_hints))
    clear_cache()

    hints = load_source_hints()

    assert hints["institution_hosts"] == {}
    assert hints["public_source_domains"] == {}
    assert source_domains("BDDK'dan veri getir") == []
    assert public_fallback_plan(
        "2024 verisini bul",
        SimpleNamespace(dataset_ids=["loans"]),
        SimpleNamespace(get_dataset=lambda _id: SimpleNamespace(name="Loans", source="bddk_monthly")),
    ) is None


def test_institution_pin_matches_dotted_capital_i_and_mixed_case():
    """casefold: 'Tüik' ≠ 'TÜİK' (noktalı İ); kurum eşlemesi ASCII katlamayla yapılır."""
    assert source_domains("Tüik'ten 2024 TÜFE verisini getir") == ["tuik.gov.tr"]
    assert source_domains("Bist'ten endeks verisini getir") == ["borsaistanbul.com"]


def test_turkish_ordinal_suffix_is_not_a_domain():
    assert addresses("Raporun 5.sayfadaki tabloyu getir") == []
    assert addresses("bddk.gov.tr sitesinden bülteni bul") == ["bddk.gov.tr"]
    assert addresses("www.tcmb.gov.tr/evds adresini oku") == ["www.tcmb.gov.tr/evds"]


# --- Option A: açık web isteği + yerel yokluk → genel (domain-pinsiz) fallback planı -------------

def test_general_fallback_distills_query_and_flags_general():
    """Genel fallback: junk sözcükler elenir, yıl/konu kalır, scope=general ve boş domain."""
    plan = general_public_fallback_plan(
        "Peki bunu internetten araştırır mısın: 2024'te dünya faiz piyasalarında ne yaşandı?"
    )
    assert plan is not None
    assert plan["scope"] == "general"
    assert plan["include_domains"] == []
    tokens = str(plan["query"]).lower().split()
    assert "2024" in tokens
    assert any(t.startswith("faiz") for t in tokens) and any(t.startswith("piyasa") for t in tokens)
    for junk in ("bunu", "araştırır", "mısın", "internetten", "yaşandı", "peki", "ne"):
        assert junk not in tokens, junk


def test_general_fallback_gate_protects_out_of_scope():
    """web_requested kapısı out-of-scope reddini korur: web istenmeyen soruda genel yol açılmaz."""
    assert web_requested("2015 yılında konut kredisi bakiyesi ne kadardı?") is False
    assert web_requested("Bunu internetten araştırır mısın?") is True


def test_general_fallback_respects_web_forbidden():
    assert general_public_fallback_plan(
        "yalnızca veritabanı kullan, internete çıkma: 2024 konut faizi"
    ) is None
