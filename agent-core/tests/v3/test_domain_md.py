"""Domain markdown: makine bölümleri kod okur, model bölümleri bütçeye göre gömülür/lookup olur."""

from __future__ import annotations

from kkb_agent_v3.core.validator import ToolRegistry
from kkb_agent_v3.domain.loader import DOMAIN_DIR, load_domain_file, parse_markdown
from kkb_agent_v3.tools.domain_note import LookupDomainNoteTool


def test_finance_md_makine_bolumleri() -> None:
    kn = load_domain_file(DOMAIN_DIR / "finance.md")
    assert "sum" in kn.measure_rules["rate"].forbidden
    assert "pp_change" in kn.measure_rules["rate"].allowed
    assert "tcmb.gov.tr" in kn.evidence_domains
    assert len(kn.notes) >= 3 and len(kn.templates) >= 2


def test_health_md_bos_sablon_calisir() -> None:
    kn = load_domain_file(DOMAIN_DIR / "health.md")
    assert "ratio" in kn.measure_rules and kn.evidence_domains
    text, lookup = kn.render_for_prompt(1500)
    assert lookup is False


def test_dosya_yoksa_bos_bilgi() -> None:
    kn = load_domain_file("yok/boyle/bir/dosya.md")
    assert kn.sections() == {}
    assert kn.render_for_prompt(100) == ("", False)


def test_lookup_baslik_ve_yakin_eslesme() -> None:
    kn = load_domain_file(DOMAIN_DIR / "finance.md")
    body, matched = kn.lookup("alt toplam ve mükerrer sayım")
    assert body and "mükerrer" in body
    body, matched = kn.lookup("mükerrer sayım")
    assert body and matched[0].startswith("note:")
    body, cands = kn.lookup("uzay mekiği")
    assert body is None and cands


def test_butce_karari() -> None:
    kn = load_domain_file(DOMAIN_DIR / "finance.md")
    inline, lookup = kn.render_for_prompt(100_000)
    assert lookup is False and "[note: birim ve çarpan]" in inline
    index, lookup = kn.render_for_prompt(10)
    assert lookup is True and "lookup_domain_note" in index and "birim ve çarpan" in index
    assert len(index) < len(inline)


def test_lookup_araci_validator_uzerinden() -> None:
    kn = load_domain_file(DOMAIN_DIR / "finance.md")
    reg = ToolRegistry()
    reg.register(LookupDomainNoteTool(kn))
    r = reg.execute("lookup_domain_note", {"topic": "veri yok cevabı"})
    assert r.ok and "Tek paragraf" in r.content
    r = reg.execute("lookup_domain_note", {"topic": "kripto"})
    assert r.error_code == "INVALID_ARGS" and r.error.candidates


def test_tablo_ayristirma_dayanikli() -> None:
    kn = parse_markdown("""
## measure_rules

| semantic_type | allowed | forbidden | hint |
|:--|---|---|---|
| stock | last | sum | s |
| bozuk satır |
| flow | sum, avg | - | f |

## note: a
gövde a
""")
    assert set(kn.measure_rules) == {"stock", "flow"}
    assert kn.measure_rules["flow"].forbidden == ()
    assert kn.notes == {"a": "gövde a"}
