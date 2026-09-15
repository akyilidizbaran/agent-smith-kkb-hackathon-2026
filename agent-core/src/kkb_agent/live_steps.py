"""Canlı adım akışı (ADR-0079): soru çalışırken arayüze "şu an ne yapıyor" olayları.

Ajan döngüsü (`core/agent.py`) değişmez. Web katmanı soru süresince üç çağrıyı ÖRNEK düzeyinde sarar ve soru
bitince (hata olsa da) eski hâline getirir:

- `registry.execute`       → araç satırı (etiket + argüman özeti, süre, hata kodu)
- `llm.chat`               → model turu ("Soru inceleniyor", "Sonuçlar değerlendiriliyor", "Cevap yeniden yazılıyor")
- `evidence_builder.build` → "Kanıt zinciri kuruluyor"

Araç çağırmayan model turundan sonra "Cevap denetleniyor" satırı açılır: ardından yeni bir model turu gelirse taslak
doğrulama kapısında geri gönderilmiştir ("back"), araç gelirse satır düşer ("drop"), kanıt paneli ya da soru sonu gelirse
denetim geçmiştir ("ok").

Olaylar yalnız etiket ve argüman özeti taşır; modelin serbest metni ve araç çıktısı gönderilmez. Doğrulanmamış bir sayı
ekrana düşmesin diye cevap metni de akıtılmaz: nihai cevap doğrulama kapılarından geçtikten sonra tek parça gelir,
arayüz onu yazım animasyonuyla açar.
"""

from __future__ import annotations

import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

Emit = Callable[[dict[str, Any]], None]

TOOL_LABELS: dict[str, str] = {
    "lakehouse_search": "Veri kataloğunda aranıyor",
    "lakehouse_describe": "Tablo yapısı inceleniyor",
    "lakehouse_distinct_values": "Kolon değerleri listeleniyor",
    "lakehouse_query": "Veri havuzunda sorgu çalıştırılıyor",
    "workspace_show": "Tablo ekrana hazırlanıyor",
    "workspace_query": "Çalışma tablosu sorgulanıyor",
    "workspace_join": "Tablolar birleştiriliyor",
    "workspace_compute_column": "Yeni kolon hesaplanıyor",
    "workspace_add_column": "Kolon ekleniyor",
    "workspace_real_value": "Reel değer hesaplanıyor",
    "chart": "Grafik çiziliyor",
    "anomaly_detect": "Olağandışı değerler aranıyor",
    "change_points": "Kırılma noktaları aranıyor",
    "lead_lag": "Öncül–ardıl ilişkisi ölçülüyor",
    "gold_align": "Seriler aynı takvime hizalanıyor",
    "gold_decompose": "Seri bileşenlerine ayrılıyor",
    "gold_join": "Gold tabloları birleştiriliyor",
    "web_search": "Web'de aranıyor",
    "web_url": "Sayfa ya da dosya okunuyor",
    "ingest_from_url": "Kaynak taslak seri olarak alınıyor",
    "ingest_source": "Kaynaktan veri çekiliyor",
    "promote_draft": "Taslak onay denetiminden geçiriliyor",
}

# Argüman özeti için bakılan alanlar (öncelik sırası). Amaç cümlesi modelin niyetidir; SQL en sona kalır.
_DETAIL_KEYS = ("purpose", "query", "question", "dataset_id", "dataset", "series_id", "table", "title", "url", "source",
                "column_name", "column", "expression", "sql")
_UPLOAD_PREFIX = re.compile(r"^[0-9a-f]{8}_(?=\w)")
DETAIL_MAX = 110


def tool_label(name: str | None) -> str:
    if not name:
        return ""
    return TOOL_LABELS.get(name, f"{name} çalışıyor")


def _short_locator(text: str) -> str:
    """Adres → alan adı + yolun son parçası; yerel yol → yalnız dosya adı (sunucudaki dizin ekrana çıkmaz)."""
    m = re.match(r"^https?://([^/?#]+)([^?#]*)", text)
    if m:
        host = m.group(1).removeprefix("www.")
        tail = [p for p in m.group(2).split("/") if p]
        return host + (f"/…/{tail[-1]}" if len(tail) > 1 else (f"/{tail[0]}" if tail else ""))
    return _UPLOAD_PREFIX.sub("", Path(text).name) or text


def args_detail(name: str | None, args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    for key in _DETAIL_KEYS:
        value = args.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        text = " ".join(value.split())
        if key in ("url", "source"):
            text = _short_locator(text)
        elif key in ("query", "question"):
            text = f"“{text}”"
        return text if len(text) <= DETAIL_MAX else text[: DETAIL_MAX - 1].rstrip() + "…"
    return ""


class LiveSteps:
    """Olay üretici. `emit` hata verirse (istemci koptu vb.) soru etkilenmez."""

    def __init__(self, emit: Emit) -> None:
        self._emit = emit
        self._next_id = 0
        self._model_turns = 0
        self._check: int | None = None

    def _send(self, **event: Any) -> None:
        try:
            self._emit({"type": "step", **event})
        except Exception:  # noqa: BLE001 — akış kopsa da ajan çalışmaya devam eder
            pass

    def _new(self, kind: str, label: str, detail: str = "") -> int:
        self._next_id += 1
        self._send(id=self._next_id, kind=kind, state="run", label=label, detail=detail)
        return self._next_id

    def _close_check(self, state: str, **extra: Any) -> None:
        if self._check is not None:
            self._send(id=self._check, state=state, **extra)
            self._check = None

    @staticmethod
    def _ms(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)

    # ---- sarmalayıcılar
    def wrap_chat(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def chat(*args: Any, **kwargs: Any) -> Any:
            if self._check is not None:
                self._close_check("back", label="Taslak geri gönderildi", detail="doğrulama kapısı yeniden yazdırıyor")
                label = "Cevap yeniden yazılıyor"
            else:
                label = "Soru inceleniyor" if self._model_turns == 0 else "Sonuçlar değerlendiriliyor"
            self._model_turns += 1
            sid = self._new("model", label)
            started = time.perf_counter()
            try:
                response = original(*args, **kwargs)
            except Exception as exc:
                self._send(id=sid, state="fail", ms=self._ms(started), detail=type(exc).__name__)
                raise
            calls = list(getattr(response, "tool_calls", None) or [])
            self._send(id=sid, state="ok", ms=self._ms(started))   # seçilen araç bir sonraki satırda zaten görünür
            if not calls:
                self._check = self._new("check", "Cevap denetleniyor", "sayılar araç çıktılarıyla karşılaştırılıyor")
            return response
        return chat

    def wrap_execute(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def execute(name: str, args: Any, *rest: Any, **kwargs: Any) -> Any:
            self._close_check("drop")      # metin içi araç çağrısı (yerel tool-calling yok): denetim değilmiş
            sid = self._new("tool", tool_label(name), args_detail(name, args))
            started = time.perf_counter()
            try:
                result = original(name, args, *rest, **kwargs)
            except Exception as exc:
                self._send(id=sid, state="fail", ms=self._ms(started), detail=type(exc).__name__)
                raise
            ok = bool(getattr(result, "ok", True))
            error = getattr(result, "error", None)
            self._send(id=sid, state="ok" if ok else "fail", ms=self._ms(started),
                       **({} if ok else {"detail": str(getattr(error, "error_code", "") or "hata")}))
            return result
        return execute

    def wrap_build(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def build(*args: Any, **kwargs: Any) -> Any:
            self._close_check("ok", detail="")
            sid = self._new("evidence", "Kanıt zinciri kuruluyor", "sayı → tablo → sorgu → kaynak")
            started = time.perf_counter()
            try:
                panel = original(*args, **kwargs)
            except Exception as exc:
                self._send(id=sid, state="fail", ms=self._ms(started), detail=type(exc).__name__)
                raise
            self._send(id=sid, state="ok", ms=self._ms(started))
            return panel
        return build

    def finish(self) -> None:
        self._close_check("ok", detail="")


@contextmanager
def live_hooks(agent: Any, emit: Emit) -> Iterator[LiveSteps]:
    """Soru süresince sarmalayıcıları kurar; çıkışta her birini eski hâline getirir (istisnada da)."""
    live = LiveSteps(emit)
    installed: list[tuple[Any, str, Any, bool]] = []

    def install(obj: Any, attr: str, wrap: Callable[[Callable[..., Any]], Callable[..., Any]]) -> None:
        original = getattr(obj, attr, None) if obj is not None else None
        if not callable(original):
            return
        own = attr in getattr(obj, "__dict__", {})
        try:
            setattr(obj, attr, wrap(original))
        except Exception:  # noqa: BLE001 — sarılamayan nesne (slots vb.) yalnız canlı satır üretmez
            return
        installed.append((obj, attr, original, own))

    install(getattr(agent, "registry", None), "execute", live.wrap_execute)
    install(getattr(agent, "llm", None), "chat", live.wrap_chat)
    install(getattr(agent, "evidence_builder", None), "build", live.wrap_build)
    try:
        yield live
    finally:
        live.finish()
        for obj, attr, original, own in reversed(installed):
            try:
                if own:
                    setattr(obj, attr, original)
                else:
                    delattr(obj, attr)
            except Exception:  # noqa: BLE001
                pass


__all__ = ["TOOL_LABELS", "LiveSteps", "args_detail", "live_hooks", "tool_label"]
