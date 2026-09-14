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


class EmbeddingCache:
    """Katalog vektörleri diskte: anahtar model + kimlik listesi + metinlerin sha256'sı.
    Katalog değişince anahtar değişir, eski dosya kalır (küçük), yenisi yazılır."""

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
        return arr.astype(np.float32).tolist()

    def put(self, model: str, ids: Sequence[str], texts: Sequence[str], vectors: Sequence[Sequence[float]]) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{self._key(model, ids, texts)}.npy"
        np.save(path, np.asarray(vectors, dtype=np.float32))
        (self.directory / f"{path.stem}.json").write_text(
            json.dumps({"model": model, "count": len(ids), "dimension": len(vectors[0]) if vectors else 0}), encoding="utf-8")
        return path


__all__ = ["EmbeddingCache", "MiaEmbedder"]
