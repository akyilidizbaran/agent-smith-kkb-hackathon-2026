"""Sohbet kaydı (ADR-0084): her sohbet `DATA_ROOT/conversations/<kimlik>/` altında durur; uygulama kapanıp açılınca kaldığı yerden sürer.

Kayıt cevaptan SONRA yazılır; model turlarının yanında milisaniyelik bir iştir. Dosyalar:
- `meta.json`: başlık, zaman, soru sayısı, profil, veri dönemi (tam sıfırlamadan önceki sohbet işaretlenir), yüklemeler
- `answers.json`: arayüzün çizdiği tam cevap yükleri (metin, tablo önizlemesi, kanıt, iz, grafik)
- `state.pkl`: ajanın o sohbetteki çalışma durumu (analiz tablosu ve geçmişi, konuşma hafızası, dışa aktarım tabloları).
  Yalnız bu sunucunun kendi yazdığı, sunucunun ürettiği kimlikli dizinden okunur; kullanıcı dosyası hiçbir zaman pickle ile açılmaz.
Tam veri sıfırlaması bu dizine dokunmaz (sıfırlama hedefleri arasında değil); sıfırlama yalnız `epoch.json` sayacını artırır.
"""

from __future__ import annotations

import json
import logging
import pickle
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
CONVERSATION_ID = re.compile(r"^[0-9a-f]{12}$")


def new_conversation_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def conversation_title(question: str, limit: int = 60) -> str:
    """İlk sorudan başlık; model çağrısı yok. Yükleme satırları ("Dosya: …") başlığa girmez."""
    lines = [ln for ln in str(question or "").splitlines() if not ln.strip().startswith("Dosya:")]
    text = re.sub(r"\s+", " ", " ".join(lines)).strip() or "Dosya analizi"
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


class ConversationStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _dir(self, cid: str) -> Path:
        if not CONVERSATION_ID.match(str(cid or "")):
            raise KeyError(cid)
        return self.root / cid

    @property
    def epoch(self) -> int:
        """Tam veri sıfırlama sayacı: sohbetin kaydındaki dönem bundan küçükse cevapları eski veriye aittir."""
        try:
            return int(json.loads((self.root / "epoch.json").read_text(encoding="utf-8")).get("epoch", 0))
        except (OSError, ValueError, AttributeError):
            return 0

    def bump_epoch(self) -> int:
        value = self.epoch + 1
        self.root.mkdir(parents=True, exist_ok=True)
        _write_atomic(self.root / "epoch.json", json.dumps({"epoch": value, "at": now_iso()}).encode("utf-8"))
        return value

    def set_active(self, cid: str) -> None:
        """Kullanıcının en son açık tuttuğu sohbet: uygulama yeniden açılınca bu açılır (kayıt tarihi değil).
        Sohbetin son kullanım zamanı da yazılır; liste en son kullanılanı en üstte gösterir."""
        d = self._dir(cid)
        self.root.mkdir(parents=True, exist_ok=True)
        _write_atomic(self.root / "active.json", json.dumps({"id": cid, "at": now_iso()}).encode("utf-8"))
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return                                        # henüz kaydedilmemiş (sorusuz) sohbet
        meta.update(used_ns=time.time_ns(), used_at=now_iso())
        _write_atomic(d / "meta.json", json.dumps(meta, ensure_ascii=False).encode("utf-8"))

    def last_active(self) -> str | None:
        try:
            cid = str(json.loads((self.root / "active.json").read_text(encoding="utf-8")).get("id") or "")
        except (OSError, ValueError, AttributeError):
            return None
        return cid if self.exists(cid) else None

    def exists(self, cid: str) -> bool:
        try:
            return (self._dir(cid) / "meta.json").is_file()
        except KeyError:
            return False

    def listing(self) -> list[dict[str, Any]]:
        """Kayıtlı sohbetler, en son kullanılan (soru sorulan ya da açılan) başta. Meta yazılmamış (yarım) kayıt listelenmez."""
        if not self.root.is_dir():
            return []
        current = self.epoch
        items: list[dict[str, Any]] = []
        for d in self.root.iterdir():
            if not (d.is_dir() and CONVERSATION_ID.match(d.name)):
                continue
            try:
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            items.append({**meta, "id": d.name, "stale": int(meta.get("epoch", 0) or 0) < current})
        return sorted(items, key=lambda m: max(int(m.get("saved_ns") or 0), int(m.get("used_ns") or 0)), reverse=True)

    def save(self, cid: str, *, meta: dict[str, Any], answers: list[Any], state: dict[str, Any]) -> None:
        meta = {**meta, "saved_ns": time.time_ns()}   # sıralama anahtarı: aynı saniyede kaydedilen iki sohbet de doğru sırada
        d = self._dir(cid)
        d.mkdir(parents=True, exist_ok=True)
        _write_atomic(d / "answers.json", json.dumps(answers, ensure_ascii=False).encode("utf-8"))
        try:
            blob = pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as exc:  # noqa: BLE001 — çalışma durumu yazılamazsa sohbet metni ve kanıtlar yine kaydedilir
            log.warning("sohbet %s çalışma durumu kaydedilemedi: %s", cid, exc)
        else:
            _write_atomic(d / "state.pkl", blob)
        _write_atomic(d / "meta.json", json.dumps(meta, ensure_ascii=False).encode("utf-8"))   # en son: liste yalnız tamam kayıtları görür

    def load(self, cid: str) -> tuple[dict[str, Any], list[Any], dict[str, Any]]:
        d = self._dir(cid)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        answers = json.loads((d / "answers.json").read_text(encoding="utf-8")) if (d / "answers.json").is_file() else []
        state: Any = {}
        if (d / "state.pkl").is_file():
            try:
                state = pickle.loads((d / "state.pkl").read_bytes())  # noqa: S301 — sunucunun kendi yazdığı dosya (modül notu)
            except Exception as exc:  # noqa: BLE001 — kod değişip eski durum okunamazsa sohbet yine açılır, çalışma alanı boş başlar
                log.warning("sohbet %s çalışma durumu okunamadı: %s", cid, exc)
                state = {}
        return meta, answers, state if isinstance(state, dict) else {}

    def delete(self, cid: str) -> None:
        shutil.rmtree(self._dir(cid), ignore_errors=True)


__all__ = ["CONVERSATION_ID", "ConversationStore", "conversation_title", "new_conversation_id", "now_iso"]
