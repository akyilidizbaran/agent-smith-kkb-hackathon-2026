"""Erişim politikası — gözlemden sonuca, sonuçtan karara; hepsi deterministik.

Üç fonksiyon, üç ayrı soru:

  classify_access(...)      HTTP'nin söylediğinden AccessOutcome üret
  detect_source_constraint  kullanıcı kaynağı sabitledi mi
  decide(...)               sonuç + kısıt → harness ne yapacak

Hiçbiri LLM'e sormaz. Modelin "bu site beni engelledi mi?" diye yorum yapması
istenmez: 403 bir 403'tür, reCAPTCHA gövdesi bir reCAPTCHA gövdesidir. Model
yalnız kararın çıktısını okur ve kullanıcıya iletir.

Credential ilkesi: bu modül bir anahtarın **var olup olmadığını** bilir, değerini
asla okumaz, loglamaz, mesaja koymaz.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from urllib.parse import urlparse

from ..contracts.access import (
    AccessEvidence,
    AccessOption,
    AccessOutcome,
    FallbackDecision,
    SourceConstraint,
)
from .errors import ToolError

# --------------------------------------------------------------------------- işaretler
# Gövdede geçtiğinde "bu bir sayfa değil, bir engel" dedirten ifadeler. Küçük harfe
# indirilmiş metinde aranır. Liste kısa ve somut: gerçek sitelerde görülenlerden
# (S&P: "Security Controls Triggered"; Cloudflare: "Just a moment", "cf-chl";
# Statista/REIDIN: reCAPTCHA'lı kayıt formu).
_BOT_MARKERS = (
    "security controls triggered",
    "access denied",
    "are you a robot",
    "bot detection",
    "just a moment",
    "cf-chl",
    "attention required",
    "unusual traffic",
)
_CAPTCHA_MARKERS = ("recaptcha", "hcaptcha", "captcha")
_PAYWALL_MARKERS = (
    "subscribe to continue",
    "subscription required",
    "paywall",
    "üyelik gerek",
    "üye girişi yap",
    "abone olun",
    "premium içerik",
)
_LOGIN_URL_MARKERS = ("login", "signin", "sign-in", "sign_in", "giris", "giriş", "/auth", "oauth", "sso")

# ------------------------------------------------------------------ credential varlığı
# Host → env anahtar adı. Değer hiçbir zaman buradan geçmez; yalnız "var mı" sorulur.
_KNOWN_CREDENTIAL_ENV: dict[str, str] = {
    "evds2.tcmb.gov.tr": "EVDS_API_KEY",
    "evds3.tcmb.gov.tr": "EVDS_API_KEY",
}


def _host(source: str) -> str:
    parsed = urlparse(source if "://" in source else f"https://{source}")
    return (parsed.hostname or "").lower()


def credential_env_name(source: str) -> str:
    """Bu kaynak için beklenen env anahtarının ADI. `KKB_CREDENTIAL_WWW_EXAMPLE_COM` gibi."""

    host = _host(source)
    if host in _KNOWN_CREDENTIAL_ENV:
        return _KNOWN_CREDENTIAL_ENV[host]
    slug = re.sub(r"[^A-Z0-9]+", "_", host.upper()).strip("_")
    return f"KKB_CREDENTIAL_{slug}"


def credential_available(source: str, environ: Mapping[str, str] | None = None) -> bool:
    """Env'de bu host için bir anahtar tanımlı mı? Değeri okunmaz, yalnız varlığı."""

    env = os.environ if environ is None else environ
    return bool(env.get(credential_env_name(source), "").strip())


# ------------------------------------------------------------------------ sınıflandırma
def _options_for(status: str, reason: str | None, *, credential: bool) -> tuple[AccessOption, ...]:
    upload = AccessOption("upload_file", "Dosyayı siz yükleyin",
                          "Kaynaktan indirdiğiniz CSV/XLSX/PDF'i verin; aynı yoldan işlerim.")
    alternative = AccessOption("alternative_source", "Başka bir kaynak arayayım",
                               "Aynı veriyi yayımlayan başka bir kurum/sayfa; kaynak değişikliği cevapta belirtilir.")
    retry = AccessOption("retry_later", "Biraz sonra tekrar deneyeyim",
                         "Kaynak istek sınırı uyguluyor; bekleyip yeniden denenebilir.")
    use_cred = AccessOption("use_credential", "Ekip hesabıyla devam edeyim",
                            "Bu kaynak için tanımlı bir anahtar var; onunla yeniden denerim.")
    if status == "needs_credential":
        return ((use_cred,) if credential else ()) + (upload, alternative)
    if status == "blocked":
        return (upload, alternative) + ((retry,) if reason == "rate_limited" else ())
    if status == "not_found":
        return (alternative, upload)
    return ()


def classify_access(
    source: str,
    *,
    http_status: int | None,
    final_url: str | None = None,
    body_excerpt: str = "",
    robots_disallow: bool = False,
    environ: Mapping[str, str] | None = None,
) -> AccessOutcome:
    """HTTP gözlemlerinden erişim sonucu. Sıra önemli: en kesin işaret önce.

    `http_status=None` → istek hiç tamamlanmadı (DNS, timeout, TLS).
    """

    body = (body_excerpt or "").lower()
    final = (final_url or "").lower()
    credential = credential_available(source, environ)
    hit_bot = tuple(m for m in _BOT_MARKERS if m in body)
    hit_captcha = tuple(m for m in _CAPTCHA_MARKERS if m in body)
    hit_paywall = tuple(m for m in _PAYWALL_MARKERS if m in body)
    login_redirect = bool(final) and final != source.lower() and any(m in final for m in _LOGIN_URL_MARKERS)
    markers = hit_bot + hit_captcha + hit_paywall
    evidence = AccessEvidence(
        http_status=http_status, final_url=final_url, markers=markers,
        robots_disallow=robots_disallow, credential_available=credential,
    )

    def out(status, reason, message):
        return AccessOutcome(
            status=status, source=source, message=message, reason=reason,
            options=_options_for(status, reason, credential=credential), evidence=evidence,
        )

    if robots_disallow:
        return out("blocked", "robots_disallow",
                   "Kaynağın robots.txt dosyası bu sayfanın otomatik çekilmesine izin vermiyor.")
    if http_status is None:
        return out("blocked", "unreachable",
                   "Kaynağa ulaşılamadı (ağ, zaman aşımı ya da sertifika hatası).")
    if http_status in (404, 410):
        return out("not_found", "gone", "Belirtilen adreste böyle bir sayfa yok.")
    if http_status == 429:
        return out("blocked", "rate_limited", "Kaynak istek sınırı uyguladı (429).")
    if http_status == 401:
        return out("needs_credential", "auth_required", "Kaynak kimlik doğrulaması istiyor (401).")
    if login_redirect or (300 <= http_status < 400 and any(m in final for m in _LOGIN_URL_MARKERS)):
        return out("needs_credential", "login_redirect", "Kaynak giriş sayfasına yönlendirdi; içerik üyelik arkasında.")
    if http_status == 403:
        if hit_bot or hit_captcha:
            return out("blocked", "bot_challenge",
                       "Kaynak otomatik istemciyi engelledi; bu engel hesapla da aşılmaz ve aşılmaya çalışılmaz.")
        return out("needs_credential", "forbidden", "Kaynak erişimi reddetti (403); hesap gerekebilir.")
    if 200 <= http_status < 300:
        if hit_captcha:
            return out("blocked", "captcha", "Sayfa CAPTCHA istiyor; otomatik olarak geçilmez.")
        if hit_bot:
            return out("blocked", "bot_challenge", "Sayfa bot denetimi gösteriyor; otomatik olarak geçilmez.")
        if hit_paywall:
            return out("needs_credential", "paywall", "İçerik ücretli üyelik arkasında.")
        return AccessOutcome(status="ok", source=source, message="Erişildi.", evidence=evidence)
    if 500 <= http_status:
        return out("blocked", "unreachable", f"Kaynak sunucu hatası döndürdü ({http_status}).")
    return out("blocked", "forbidden", f"Beklenmeyen yanıt ({http_status}).")


# ------------------------------------------------------------------ kaynak sabitleme
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
_PIN_PHRASES = re.compile(
    r"\b(?:bu|şu|verdiğim|belirttiğim|gönderdiğim|yukarıdaki)\s+"
    r"(?:site|link|url|kaynak|adres|sayfa)(?:'?[dt][ae]n)\b",
    re.I,
)
_INSTITUTIONS = ("TCMB", "BDDK", "TÜİK", "TUİK", "TUIK", "EVDS", "Borsa İstanbul", "BİST", "Hazine", "SPK", "TBB")
_INSTITUTION_PIN = re.compile(
    r"\b(" + "|".join(re.escape(i) for i in _INSTITUTIONS) + r")(?:'?[dt][ae]n|\s+(?:kaynağından|sitesinden|verisinden))\b",
    re.I,
)
_ONLY = re.compile(r"\b(?:sadece|yalnızca|yalnız)\b", re.I)


def detect_source_constraint(question: str) -> SourceConstraint:
    """Soru bir kaynağı sabitliyor mu? Tutucu: emin değilse serbest.

    Sabitleyen üç kalıp: soruda bir URL var; "bu siteden / şu linkten" gibi
    işaret ifadesi var; bir kurum adı "-den getir" hâlinde geçiyor. "Sadece/yalnızca"
    tek başına sabitlemez, kurum adıyla birlikte sabitlemeyi güçlendirir.
    """

    text = question or ""
    url = _URL_RE.search(text)
    if url:
        return SourceConstraint(pinned=True, source_ref=url.group(0), phrase=url.group(0))
    phrase = _PIN_PHRASES.search(text)
    if phrase:
        return SourceConstraint(pinned=True, source_ref=None, phrase=phrase.group(0))
    inst = _INSTITUTION_PIN.search(text)
    if inst:
        return SourceConstraint(pinned=True, source_ref=inst.group(1), phrase=inst.group(0))
    return SourceConstraint(pinned=False)


# ------------------------------------------------------------------------------- karar
def decide(outcome: AccessOutcome, constraint: SourceConstraint) -> FallbackDecision:
    """Mentörün kuralı, kod olarak.

    - erişildi → devam.
    - erişilemedi ve kaynak sabit → **sor**; başka kaynağın verisi bu kaynaktan gelmiş
      gibi kullanılmaz.
    - erişilemedi ve kaynak serbest → alternatif denenebilir, ama **açıkça söylenerek**.
    """

    if outcome.ok:
        return FallbackDecision(action="proceed", must_disclose=False)
    where = constraint.source_ref or outcome.source
    if constraint.pinned:
        return FallbackDecision(
            action="ask_user",
            must_disclose=True,
            disclosure=(
                f"Belirttiğiniz kaynağa ({where}) erişemedim: {outcome.message} "
                "Kaynağı siz belirttiğiniz için değiştirmeden önce soruyorum."
            ),
            options=outcome.options,
        )
    return FallbackDecision(
        action="try_alternative",
        must_disclose=True,
        disclosure=(
            f"{where} kaynağına erişemedim: {outcome.message} "
            "Aynı veriyi başka bir kaynakta arayacağım; bulursam kaynak değişikliğini cevapta belirteceğim."
        ),
        options=outcome.options,
    )


def render_for_model(outcome: AccessOutcome, decision: FallbackDecision) -> str:
    """Modele giden metin. Sessiz geçiş yok: sebep, seçenekler ve kural her zaman yazılır."""

    lines = [f"ERİŞİM[{outcome.status}]: {outcome.message}"]
    if outcome.reason:
        lines.append(f"SEBEP: {outcome.reason}")
    if decision.options:
        lines.append("SEÇENEKLER: " + " | ".join(f"{o.kind}: {o.label}" for o in decision.options))
    rule = {
        "proceed": "Erişildi; devam et.",
        "ask_user": "KAYNAK SABİT. Kaynak değiştirme, alternatif verisi kullanma; kullanıcıya seçenekleri sun ve sor.",
        "try_alternative": "Kaynak serbest. Alternatif kaynak denenebilir; bulursan kaynak değişikliğini cevapta AÇIKÇA yaz.",
    }[decision.action]
    lines.append("KURAL: " + rule)
    if decision.disclosure:
        lines.append("KULLANICIYA: " + decision.disclosure)
    return "\n".join(lines)


_CODE = {"needs_credential": "NEEDS_CREDENTIAL", "blocked": "ACCESS_BLOCKED", "not_found": "SOURCE_NOT_FOUND"}


def to_tool_error(outcome: AccessOutcome, decision: FallbackDecision) -> ToolError:
    """Araç sonucuna dönüşüm: hata zarfı (ADR-0025) ile aynı dil, `access` katmanı."""

    return ToolError(
        error_code=_CODE[outcome.status],  # type: ignore[arg-type]
        message=render_for_model(outcome, decision),
        hint=None,
        candidates=[o.kind for o in decision.options],
        layer="access",
    )


__all__ = [
    "classify_access",
    "credential_available",
    "credential_env_name",
    "decide",
    "detect_source_constraint",
    "render_for_model",
    "to_tool_error",
]
