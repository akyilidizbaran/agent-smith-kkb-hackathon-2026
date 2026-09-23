"""İsteğe bağlı gerçek-tarayıcı edinme katmanı.

Statik HTTP okuyucusu boş bir JavaScript uygulama kabuğu döndürürse, kullanıcının zaten
yetkilendirdiği URL normal Chrome ile açılır. Kaynağa özel etkileşimler bu modüldeki adaptör
kayıt defterinde yaşar; ``web_url`` çekirdeğine kurum adı/selector gömülmez.

Playwright paketi veya sistem Chrome'u bulunmuyorsa uygulama başlamaya devam eder ve çağrı
``None`` ile güvenli statik fallback'e döner. CAPTCHA/WAF atlatılmaz; normal kullanıcı
tarayıcısında meşru biçimde çalışan sayfa akışı kullanılır.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from ..contracts.access import AccessEvidence, AccessOutcome
from ..core.access_policy import classify_access
from ..core.web_routing import matched_external_source
from .crawl import CrawlBudget, CrawlResult, VisitedPage
from .fetch import FetchResult, private_host
from .html import extract_page


log = logging.getLogger(__name__)

# Bot korumasına takılan host bir süre yeniden denenmez (canlı arayüz, 23 Eyl): TEFAS başsız tarayıcıya "Request Rejected"
# döndürüyordu; adaptör her çağrıda 30 sn form öğesi bekleyip sessizce düşüyor, model aynı adresi üç kez deniyordu.
_BLOCK_TTL_S = 600.0
_BLOCKED_HOSTS: dict[str, tuple[float, AccessOutcome]] = {}


class BrowserBlocked(RuntimeError):
    """Gerçek tarayıcıda açılan sayfa bir erişim engeli (bot denetimi / CAPTCHA). Engel aşılmaz; sonuç olarak döner."""

    def __init__(self, outcome: AccessOutcome) -> None:
        super().__init__(outcome.message)
        self.outcome = outcome


def _guard_block(page: Any, url: str) -> None:
    """Açılan sayfa bir engel sayfasıysa hemen dur: erişim sınıflandırıcısıyla aynı işaretler (ADR-0028)."""
    try:
        body = page.content()[:20000]
    except Exception:  # noqa: BLE001 — içerik okunamadıysa karar verilmez
        return
    outcome = classify_access(url, http_status=200, final_url=getattr(page, "url", url), body_excerpt=body)
    if not outcome.ok and outcome.reason in {"bot_challenge", "captcha"}:
        raise BrowserBlocked(outcome)


@dataclass(frozen=True)
class BrowserPayload:
    content: bytes
    media_type: str
    name: str
    title: str
    final_url: str
    notes: tuple[str, ...] = ()


def _period(question: str) -> tuple[str, str]:
    values = [f"{year}-{month}" for year, month in re.findall(r"\b(20\d{2})(0[1-9]|1[0-2])\b", question)]
    if len(values) >= 2:
        return values[0], values[-1]
    years = re.findall(r"\b(20\d{2})\b", question)
    if len(years) >= 2:
        return f"{years[0]}-01", f"{years[-1]}-12"
    raise ValueError("aylık başlangıç ve bitiş dönemi (YYYYMM) bulunamadı")


_MONTHS = {
    "01": "Ocak", "02": "Şubat", "03": "Mart", "04": "Nisan",
    "05": "Mayıs", "06": "Haziran", "07": "Temmuz", "08": "Ağustos",
    "09": "Eylül", "10": "Ekim", "11": "Kasım", "12": "Aralık",
}


def _choose(page: Any, label: str, value: str) -> None:
    combo = page.get_by_role("combobox", name=label)
    combo.focus()
    page.keyboard.press("ArrowDown")
    page.get_by_role("option", name=value, exact=True).click()


def _tefas(page: Any, url: str, question: str, timeout_ms: int) -> BrowserPayload:
    """TEFAS Toplam İşlem Hacmi formunu normal browser oturumunda çalıştır.

    Endpoint/şema 23 Eyl 2026'da gerçek Chrome network akışından doğrulandı. Bearer token veya
    cookie dışarı alınmaz; POST isteğini sayfanın kendi JavaScript'i yapar ve yalnız JSON cevabı
    aynı browser oturumunda okunur.
    """

    start, end = _period(question)
    page.goto("https://www.tefas.gov.tr/tr/tefas-istatistikleri", wait_until="domcontentloaded", timeout=timeout_ms)
    _guard_block(page, url)
    page.get_by_role("button", name=re.compile(r"^İşlem Hacmi Raporları")).click()
    _choose(page, "Başlangıç Yılı", start[:4])
    _choose(page, "Başlangıç Ayı", _MONTHS[start[-2:]])
    _choose(page, "Bitiş Yılı", end[:4])
    _choose(page, "Bitiş Ayı", _MONTHS[end[-2:]])
    endpoint = "/api/statistics/tefas/getFplToplamIslemHacmi"
    with page.expect_response(lambda r: endpoint in r.url and r.request.method == "POST", timeout=timeout_ms) as pending:
        page.get_by_role("button", name="Görüntüle").click()
    response = pending.value
    if not response.ok:
        raise RuntimeError(f"TEFAS rapor API HTTP {response.status}")
    body = response.json()
    if body.get("error") or body.get("errorCode"):
        raise RuntimeError(str(body.get("errorMessage") or body.get("errorCode") or "TEFAS rapor hatası"))
    rows = [row for row in (body.get("data") or []) if re.fullmatch(r"20\d{2}-(?:0[1-9]|1[0-2])", str(row.get("donem", "")))]
    if not rows:
        raise RuntimeError("TEFAS raporu aylık veri döndürmedi")
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["Dönem", "Toplam İşlem Hacmi (TL)", "Günlük Ortalama İşlem Hacmi (TL)", "Net Takas Tutarı (TL)"])
    for row in rows:
        writer.writerow([row.get("donem"), row.get("toplamIslemHacmi"), row.get("gunlukOrtalamaHacim"), row.get("netTakasTutar")])
    return BrowserPayload(
        content=out.getvalue().encode("utf-8"), media_type="text/csv", name="tefas-toplam-islem-hacmi.csv",
        title="TEFAS Toplam İşlem Hacmi Raporu", final_url=page.url,
        notes=(f"Gerçek Chrome formu ile {start}–{end} dönemi sorgulandı; {len(rows)} aylık kayıt.",),
    )


_ADAPTERS: dict[str, Callable[[Any, str, str, int], BrowserPayload]] = {"tefas": _tefas}


def _launch_kwargs(environ: Mapping[str, str]) -> dict[str, Any]:
    configured = str(environ.get("BROWSER_EXECUTABLE_PATH") or "").strip()
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise RuntimeError(f"BROWSER_EXECUTABLE_PATH bulunamadı: {path}")
        return {"executable_path": str(path)}
    # Playwright kendi browser'ını indirmeden sistem Chrome kanalını kullanır.
    return {"channel": "chrome"}


def browser_crawl_result(
    url: str,
    question: str,
    *,
    environ: Mapping[str, str] | None = None,
    timeout_ms: int = 30_000,
) -> CrawlResult | None:
    """Render edilmiş sayfayı/veri dosyasını mevcut ``CrawlResult`` sözleşmesine çevir."""

    env = dict(os.environ if environ is None else environ)
    if str(env.get("WEB_BROWSER_FALLBACK", "1")).casefold() in {"0", "false", "no", "off"}:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or private_host(parsed.hostname):
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    remembered = _BLOCKED_HOSTS.get(parsed.hostname)
    if remembered is not None and time.monotonic() - remembered[0] < _BLOCK_TTL_S:
        return _blocked_result(url, remembered[1])

    source = matched_external_source(f"{question}\n{url}") or {}
    adapter_key = str(source.get("adapter_key") or "")
    headless = str(env.get("BROWSER_HEADLESS", "true")).casefold() not in {"0", "false", "no", "off"}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless, **_launch_kwargs(env))
            try:
                context = browser.new_context(accept_downloads=True, locale="tr-TR")
                page = context.new_page()
                page.set_default_timeout(timeout_ms)
                adapter = _ADAPTERS.get(adapter_key)
                if adapter is not None:
                    payload = adapter(page, url, question, timeout_ms)
                else:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_timeout(750)
                    _guard_block(page, url)
                    payload = BrowserPayload(
                        content=page.content().encode("utf-8"), media_type="text/html", name="rendered.html",
                        title=page.title(), final_url=page.url,
                        notes=("Sayfa gerçek Chrome ile JavaScript çalıştırılarak render edildi.",),
                    )
            finally:
                browser.close()
    except BrowserBlocked as blocked:
        _BLOCKED_HOSTS[parsed.hostname] = (time.monotonic(), blocked.outcome)
        log.warning("tarayıcı: %s bot denetimiyle engellendi (%s)", parsed.hostname, blocked.outcome.reason)
        return _blocked_result(url, blocked.outcome)
    except Exception as exc:  # noqa: BLE001 — tarayıcı yoksa ya da akış bozulduysa statik sonuca dönülür
        log.warning("tarayıcı: %s açılamadı: %s: %s", parsed.hostname, type(exc).__name__, str(exc)[:200])
        return None

    now = datetime.now(timezone.utc)
    digest = hashlib.sha256(payload.content).hexdigest()
    outcome = AccessOutcome(
        status="ok", source=url, message="Kaynak gerçek tarayıcıyla açıldı.",
        evidence=AccessEvidence(http_status=200, final_url=payload.final_url),
    )
    fetched = FetchResult(
        url=url, final_url=payload.final_url, http_status=200, media_type=payload.media_type,
        content=payload.content, sha256=digest, fetched_at=now, outcome=outcome,
    )
    page_content = extract_page(payload.content, payload.media_type, payload.name)
    page_content.url = payload.final_url
    page_content.title = payload.title or page_content.title
    page_content.notes.extend(payload.notes)
    budget = CrawlBudget(max_pages=1, max_depth=0, max_seconds=max(5.0, timeout_ms / 1000))
    return CrawlResult(
        start_url=url,
        pages=[VisitedPage(url=payload.final_url, depth=0, fetch=fetched, page=page_content)],
        budget=budget,
    )


def _blocked_result(url: str, outcome: AccessOutcome) -> CrawlResult:
    """Engel, web_url'in erişim sözleşmesine giden yapısal sonuçtur: sayfa yok, sonuç 'blocked'."""
    fetched = FetchResult(
        url=url, final_url=url, http_status=200, media_type="text/html", content=b"",
        sha256=hashlib.sha256(b"").hexdigest(), fetched_at=datetime.now(timezone.utc), outcome=outcome,
    )
    return CrawlResult(start_url=url, blocked=[VisitedPage(url=url, depth=0, fetch=fetched, page=None)],
                       budget=CrawlBudget(max_pages=1, max_depth=0, max_seconds=5.0))


__all__ = ["BrowserBlocked", "BrowserPayload", "browser_crawl_result"]
