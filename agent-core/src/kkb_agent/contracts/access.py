"""Erişim sözleşmesi — bir kaynağa ulaşma girişiminin yapısal sonucu.

Mentör kararı (12 Eylül): ajan hesap açmaz, CAPTCHA aşmaz, bot engelini
dolanmaz. Erişemediği kaynakta bunu **açıkça söyler ve seçenek sunar**; kaynak
değişikliğini asla gizli yapmaz; hiç erişilemeyecek bir URL verilse bile
kontrollü biçimde geriler.

Bunun ön koşulu, "erişemedim"in bir istisna değil bir **değer** olması. Bir
istisna yalnız "olmadı" der; bu sözleşme *neden* olmadığını, *ne* yapılabileceğini
ve kaynağın kullanıcı tarafından *sabitlenip sabitlenmediğini* taşır. Ingest ve
web araçları (Architect rolü, `web_url`) bu tipi üretir; harness kararı buradan
verir; model yalnız sonucu okur.

Bu modülde ağ yok, HTTP yok, LLM yok. Yalnız tipler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

AccessStatus = Literal["ok", "needs_credential", "blocked", "not_found"]
"""Dört sonuç sınıfı. `ok` dışındaki üçü birbirinden farklı seçenekler doğurur:
credential gerekiyorsa ekip hesabı bir seçenek; bot/CAPTCHA engelinde değil."""

BlockReason = Literal[
    "auth_required",     # 401 — kimlik istiyor
    "login_redirect",    # sayfa giriş ekranına yönlendirdi
    "forbidden",         # 403, bot işareti yok — hesap gerekebilir
    "paywall",           # içerik ücretli üyelik arkasında
    "bot_challenge",     # "Security Controls Triggered", Cloudflare challenge vb.
    "captcha",           # reCAPTCHA / hCaptcha
    "rate_limited",      # 429
    "robots_disallow",   # robots.txt bu yolu yasaklıyor
    "gone",              # 404 / 410
    "unreachable",       # DNS, timeout, TLS
]

OptionKind = Literal["use_credential", "upload_file", "alternative_source", "retry_later"]


@dataclass(frozen=True)
class AccessOption:
    """Kullanıcıya sunulacak tek bir seçenek. `label` insan için, `kind` harness için."""

    kind: OptionKind
    label: str
    detail: str | None = None


@dataclass(frozen=True)
class AccessEvidence:
    """Kararın dayandığı gözlemler. Cevaba değil, kanıt paneline gider."""

    http_status: int | None = None
    final_url: str | None = None
    markers: tuple[str, ...] = ()       # gövdede yakalanan işaretler ("recaptcha", …)
    robots_disallow: bool = False
    credential_available: bool = False  # bu host için env'de anahtar var mı — DEĞERİ değil


@dataclass(frozen=True)
class AccessOutcome:
    """Bir kaynağa erişim girişiminin sonucu."""

    status: AccessStatus
    source: str
    message: str                                   # ne oldu, tek cümle, Türkçe
    reason: BlockReason | None = None
    options: tuple[AccessOption, ...] = ()
    evidence: AccessEvidence = field(default_factory=AccessEvidence)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class SourceConstraint:
    """Kullanıcı kaynağı sabitledi mi?

    "2025 enflasyonunu bul" → serbest: sonuç odaklı, alternatif kaynağa geçilebilir.
    "bu URL'den / TCMB'den getir" → sabit: kaynak sadakati bir kısıttır; başka
    kaynağın verisi ilk kaynaktan gelmiş gibi sunulmaz, önce sorulur.
    """

    pinned: bool
    source_ref: str | None = None   # URL ya da kurum adı
    phrase: str | None = None       # sabitlemeyi tetikleyen ifade — kanıt için


FallbackAction = Literal["proceed", "ask_user", "try_alternative"]


@dataclass(frozen=True)
class FallbackDecision:
    """Harness'ın kararı. `disclosure` cevaba girer; kaynak değişikliği asla sessiz değil."""

    action: FallbackAction
    must_disclose: bool
    disclosure: str | None = None
    options: tuple[AccessOption, ...] = ()


__all__ = [
    "AccessEvidence",
    "AccessOption",
    "AccessOutcome",
    "AccessStatus",
    "BlockReason",
    "FallbackAction",
    "FallbackDecision",
    "OptionKind",
    "SourceConstraint",
]
