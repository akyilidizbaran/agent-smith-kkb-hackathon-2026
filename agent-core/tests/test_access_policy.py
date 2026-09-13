"""Erişim politikası — ağ yok, LLM yok; yalnız gözlem → sonuç → karar.

Mentörün 12 Eylül kuralının kod olarak tutup tutmadığını ölçer: bypass yok,
credential değeri hiçbir yerde görünmez, erişilemeyen kaynakta sessizlik yok,
sabit kaynakta kaynak değiştirilmez.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.access_policy import (  # noqa: E402
    classify_access,
    credential_available,
    credential_env_name,
    decide,
    detect_source_constraint,
    render_for_model,
    to_tool_error,
)
from kkb_agent.core.errors import NOT_RETRYABLE  # noqa: E402

SRC = "https://www.example.com/veri"


# --------------------------------------------------------------- sınıflandırma
@pytest.mark.parametrize(
    ("kwargs", "status", "reason"),
    [
        (dict(http_status=200), "ok", None),
        (dict(http_status=404), "not_found", "gone"),
        (dict(http_status=410), "not_found", "gone"),
        (dict(http_status=429), "blocked", "rate_limited"),
        (dict(http_status=401), "needs_credential", "auth_required"),
        (dict(http_status=403), "needs_credential", "forbidden"),
        (dict(http_status=403, body_excerpt="<h1>Security Controls Triggered</h1>"), "blocked", "bot_challenge"),
        (dict(http_status=200, body_excerpt='<div class="g-recaptcha">'), "blocked", "captcha"),
        (dict(http_status=200, body_excerpt="Just a moment... cf-chl"), "blocked", "bot_challenge"),
        (dict(http_status=200, body_excerpt="Subscribe to continue reading"), "needs_credential", "paywall"),
        (dict(http_status=200, final_url="https://www.example.com/login?next=/veri"), "needs_credential", "login_redirect"),
        (dict(http_status=302, final_url="https://www.example.com/giris"), "needs_credential", "login_redirect"),
        (dict(http_status=None), "blocked", "unreachable"),
        (dict(http_status=503), "blocked", "unreachable"),
        (dict(http_status=200, robots_disallow=True), "blocked", "robots_disallow"),
    ],
)
def test_gozlemden_sonuc(kwargs, status, reason) -> None:
    out = classify_access(SRC, environ={}, **kwargs)
    assert (out.status, out.reason) == (status, reason)
    assert out.ok == (status == "ok")


def test_gercek_sitelerden_ornekler() -> None:
    """Büşra'nın denediği dört kaynak: Moody's login, S&P 403, Statista reCAPTCHA, BİST JS."""

    moodys = classify_access("https://www.moodys.com/research/x", http_status=200,
                             final_url="https://www.moodys.com/login?returnUrl=/research/x", environ={})
    sp = classify_access("https://www.spglobal.com/ratings/x", http_status=403,
                         body_excerpt="Security Controls Triggered", environ={})
    statista = classify_access("https://www.statista.com/x", http_status=200,
                               body_excerpt='<div class="g-recaptcha" data-sitekey=', environ={})
    assert moodys.status == "needs_credential"
    assert sp.status == "blocked" and sp.reason == "bot_challenge"
    assert statista.status == "blocked" and statista.reason == "captcha"


# ---------------------------------------------------------------- credential
def test_credential_yalniz_varligi_bilinir_degeri_hic_gorunmez() -> None:
    env = {"KKB_CREDENTIAL_WWW_EXAMPLE_COM": "cok-gizli-anahtar-123"}

    assert credential_env_name(SRC) == "KKB_CREDENTIAL_WWW_EXAMPLE_COM"
    assert credential_available(SRC, env) is True
    assert credential_available(SRC, {}) is False

    out = classify_access(SRC, http_status=401, environ=env)
    decision = decide(out, detect_source_constraint("bu siteden veriyi getir"))
    rendered = render_for_model(out, decision) + str(out) + str(decision)
    assert "cok-gizli-anahtar-123" not in rendered
    assert any(o.kind == "use_credential" for o in out.options)


def test_evds_bilinen_anahtar_adina_eslenir() -> None:
    assert credential_env_name("https://evds3.tcmb.gov.tr/igmevdsms-dis/series=TP.KTF12") == "EVDS_API_KEY"


def test_bot_engelinde_credential_secenek_degildir() -> None:
    """Hesap olsa bile bot/CAPTCHA engeli aşılmaz — mentörün açık kuralı."""

    env = {"KKB_CREDENTIAL_WWW_EXAMPLE_COM": "x"}
    out = classify_access(SRC, http_status=403, body_excerpt="Security Controls Triggered", environ=env)
    assert out.status == "blocked"
    assert all(o.kind != "use_credential" for o in out.options)
    assert {o.kind for o in out.options} == {"upload_file", "alternative_source"}


# ------------------------------------------------------------ kaynak sabitleme
@pytest.mark.parametrize(
    ("question", "pinned", "ref"),
    [
        ("https://www.bddk.org.tr/BultenAylik adresinden 2025 konut kredisini getir", True, "https://www.bddk.org.tr/BultenAylik"),
        ("Bu siteden 2025 aylık enflasyon verisini getir", True, None),
        ("şu linkten tabloyu çek", True, None),
        ("TCMB'den 2025 politika faizini getir", True, "TCMB"),
        ("Sadece BDDK verisinden konut kredisini göster", True, "BDDK"),
        ("2025 aylık enflasyonu bul", False, None),
        ("Konut kredisi 2025'te nasıl değişti?", False, None),
        ("TCMB politika faizi ne kadar?", False, None),   # kurum adı geçiyor ama "-den getir" yok
    ],
)
def test_kaynak_sabitleme_tutucu(question, pinned, ref) -> None:
    c = detect_source_constraint(question)
    assert c.pinned is pinned
    if ref is not None:
        assert c.source_ref == ref


# --------------------------------------------------------------------- karar
def test_erisildiyse_devam() -> None:
    out = classify_access(SRC, http_status=200, environ={})
    d = decide(out, detect_source_constraint("bu siteden getir"))
    assert d.action == "proceed" and d.must_disclose is False


def test_sabit_kaynakta_sorulur_degistirilmez() -> None:
    out = classify_access(SRC, http_status=404, environ={})
    d = decide(out, detect_source_constraint("bu siteden 2025 enflasyonunu getir"))
    assert d.action == "ask_user"
    assert d.must_disclose and "erişemedim" in d.disclosure
    assert d.options == out.options


def test_serbest_kaynakta_alternatif_ama_acikca() -> None:
    out = classify_access(SRC, http_status=404, environ={})
    d = decide(out, detect_source_constraint("2025 enflasyonunu bul"))
    assert d.action == "try_alternative"
    assert d.must_disclose and "belirteceğim" in d.disclosure


def test_modele_giden_metin_hic_sessiz_degil() -> None:
    out = classify_access(SRC, http_status=403, body_excerpt="recaptcha", environ={})
    text = render_for_model(out, decide(out, detect_source_constraint("bu siteden getir")))
    assert text.startswith("ERİŞİM[blocked]")
    assert "SEBEP: bot_challenge" in text or "SEBEP: captcha" in text
    assert "SEÇENEKLER:" in text and "upload_file" in text
    assert "KAYNAK SABİT" in text


def test_hata_zarfina_donusum_tekrar_denenemez() -> None:
    for status_code, code in ((401, "NEEDS_CREDENTIAL"), (403, "NEEDS_CREDENTIAL"), (404, "SOURCE_NOT_FOUND"), (429, "ACCESS_BLOCKED")):
        out = classify_access(SRC, http_status=status_code, environ={})
        err = to_tool_error(out, decide(out, detect_source_constraint("x")))
        assert err.error_code == code and err.layer == "access"
        assert code in NOT_RETRYABLE and err.is_retryable is False
        assert "TEKRAR DENEMEYLE ÇÖZÜLMEZ" in err.render()
