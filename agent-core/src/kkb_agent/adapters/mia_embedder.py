"""MIA embedding istemcisi — `Embedder` sözleşmesinin Kloudeks uygulaması (ADR-0043).

Aynı anahtar, aynı OpenAI-uyumlu uç (`/v1/embeddings`), `EMBEDDING_MODEL`
(Qwen3-Embedding-8B, 4096 boyut). Ölçüldü: 32 metin 1,55 s. Toplu çağrı 64'lük dilimlerle;
anahtar başlıkta, gövdede değil. Vektörler diske önbelleklenir (`EmbeddingCache`): katalog
sürümü başına bir kez hesaplanır, sorgu başına yalnız sorunun vektörü istenir.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np


class MiaEmbedder:
    def __init__(self, *, base_url: str, api_key: str, model: str, session: Any = None,
                 timeout: float = 120.0, batch_size: int = 64) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model = model
        self.dimension = 4096
        self._session = session
        self.timeout = timeout
        self.batch_size = batch_size
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        session = self._session
        if session is None:
            from ..web.session import default_session
            session = default_session()
        out: list[list[float]] = []
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        for i in range(0, len(texts), self.batch_size):
            chunk = [t if t.strip() else "-" for t in texts[i:i + self.batch_size]]
            resp = session.post(f"{self.base_url}/embeddings", json={"model": self.model, "input": chunk},
                                headers=headers, timeout=self.timeout)
            self.calls += 1
            if getattr(resp, "status_code", None) != 200:
                raise RuntimeError(f"embedding isteği {getattr(resp, 'status_code', None)} döndü")
            data = resp.json().get("data", [])
            vectors = [d["embedding"] for d in sorted(data, key=lambda d: d.get("index", 0))]
            if len(vectors) != len(chunk):
                raise RuntimeError(f"embedding yanıtı {len(vectors)} vektör döndü, {len(chunk)} beklendi")
            if vectors:
                self.dimension = len(vectors[0])
            out.extend(vectors)
        return out


def record_digest(record_id: str, text: str) -> str:
    """Tek kaydın parmak izi: kimlik + metin. Katalog sürümleri arasında değişmeyen kayıt aynı izi taşır."""
    return hashlib.sha256(record_id.encode("utf-8") + b"\x1e" + text.encode("utf-8")).hexdigest()[:20]


class EmbeddingCache:
    """Katalog vektörleri diskte: anahtar model + kimlik listesi + metinlerin sha256'sı.

    Katalog değişince tam anahtar değişir; ama yan dosyada (`.json`) her kaydın parmak izi durduğu için
    değişmeyen kayıtların vektörleri en yeni önceki sürümden alınır ve yalnız yeni/değişen kayıtlar
    hesaplanır (`reuse`). Ölçüldü (20 Eyl): Architect bir taslak seri ekleyince 6.305 serinin tamamı
    yeniden gömülüyor, ~600 sn sürüyor ve soru bütçesi (300 sn) döngüye girmeden doluyordu; artımlı
    yolda yalnız yeni seri gömülür. Eski sürüm dosyaları `prune` ile sınırlı sayıda tutulur (her biri ~100 MB)."""

    KEEP_VERSIONS = 3

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _key(self, model: str, ids: Sequence[str], texts: Sequence[str]) -> str:
        h = hashlib.sha256()
        h.update(model.encode("utf-8"))
        for i, t in zip(ids, texts):
            h.update(b"\x1f" + i.encode("utf-8") + b"\x1e" + t.encode("utf-8"))
        return h.hexdigest()[:24]

    def get(self, model: str, ids: Sequence[str], texts: Sequence[str]) -> list[list[float]] | None:
        path = self.directory / f"{self._key(model, ids, texts)}.npy"
        if not path.is_file():
            return None
        arr = np.load(path)
        self._adopt_sidecar(path, model, ids, texts, arr.shape[0])
        return arr.astype(np.float32).tolist()

    def _adopt_sidecar(self, path: Path, model: str, ids: Sequence[str], texts: Sequence[str], rows: int) -> None:
        """Bu değişiklikten önce yazılmış sürümün yan dosyasına kayıt izlerini ekle (tam anahtar tuttuğu için
        kimlik/metin listesi elimizde). Böylece mevcut ~100 MB'lık önbellek yeniden hesaplanmadan artımlı yola girer."""
        sidecar = path.with_suffix(".json")
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
        except (OSError, ValueError):
            meta = {}
        if isinstance(meta.get("records"), list) or rows != len(ids):
            return
        meta.update({"model": model, "count": len(ids), "records": [record_digest(i, t) for i, t in zip(ids, texts)]})
        try:
            sidecar.write_text(json.dumps(meta), encoding="utf-8")
        except OSError:
            pass

    def reuse(self, model: str, ids: Sequence[str], texts: Sequence[str]) -> dict[str, list[float]]:
        """Aynı modelin en yeni önbellek sürümünden, parmak izi tutan kayıtların vektörleri: {parmak izi: vektör}.

        Yan dosyası kayıt izlerini taşımayan eski sürümler (bu değişiklikten önce yazılanlar) atlanır; onlar
        için davranış eskisi gibi tam hesaptır. Bozuk/eksik dosya sessizce yok sayılır: önbellek hızlandırıcıdır,
        doğruluk kaynağı değil."""
        wanted = {record_digest(i, t) for i, t in zip(ids, texts)}
        if not wanted or not self.directory.is_dir():
            return {}
        sidecars = sorted(self.directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for sidecar in sidecars:
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            digests = meta.get("records")
            if meta.get("model") != model or not isinstance(digests, list):
                continue
            npy = sidecar.with_suffix(".npy")
            if not npy.is_file():
                continue
            try:
                arr = np.load(npy, mmap_mode="r")
            except (OSError, ValueError):
                continue
            if arr.shape[0] != len(digests):
                continue
            hits = {d: arr[row].astype(np.float32).tolist() for row, d in enumerate(digests) if d in wanted}
            if hits:
                return hits
        return {}

    def put(self, model: str, ids: Sequence[str], texts: Sequence[str], vectors: Sequence[Sequence[float]]) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{self._key(model, ids, texts)}.npy"
        np.save(path, np.asarray(vectors, dtype=np.float32))
        (self.directory / f"{path.stem}.json").write_text(
            json.dumps({"model": model, "count": len(ids), "dimension": len(vectors[0]) if vectors else 0,
                        "records": [record_digest(i, t) for i, t in zip(ids, texts)]}), encoding="utf-8")
        self.prune(model, keep=self.KEEP_VERSIONS, current=path)
        return path

    def prune(self, model: str, *, keep: int, current: Path) -> int:
        """Aynı modelin en yeni `keep` sürümü dışındakileri sil (her sürüm ~100 MB). Silinen dosya sayısı döner."""
        versions = []
        for sidecar in self.directory.glob("*.json"):
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if meta.get("model") == model:
                versions.append(sidecar)
        versions.sort(key=lambda p: (p.with_suffix(".npy") == current, p.stat().st_mtime), reverse=True)
        removed = 0
        for sidecar in versions[keep:]:
            for p in (sidecar, sidecar.with_suffix(".npy")):
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed


__all__ = ["EmbeddingCache", "MiaEmbedder", "record_digest"]
