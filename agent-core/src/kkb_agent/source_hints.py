"""Kaynağa özel ipuçlarının tek yükleyicisi (M03-T04, ADR-0060).

Çekirdek (facets, access_policy) kaynak adlarını kodda taşımaz; bu dosyadan okur. Varsayılan paket içindeki
`config_data/source_hints.json`; `SOURCE_HINTS_FILE` ortam değişkeni başka bir dosya verir. Dosya yoksa ya da
boşsa motor çalışmaya devam eder: kaynak yüzü, anahtar-host eşlemesi ve kurum sabitleme ipucu olmaz.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parent / "config_data" / "source_hints.json"
EMPTY: dict[str, Any] = {"source_words": {}, "credential_env_by_host": {}, "institutions": (), "source_names": {},
                         "derived_sources": (), "official_hosts": (), "url_patterns": (),
                         "institution_hosts": {}, "public_source_domains": {}, "financial_sources": {}}


@lru_cache(maxsize=4)
def _load(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return dict(EMPTY)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(EMPTY)
    return {
        "source_words": {str(k): tuple(map(str, v)) for k, v in (data.get("source_words") or {}).items()},
        "credential_env_by_host": {str(k).lower(): str(v) for k, v in (data.get("credential_env_by_host") or {}).items()},
        "institutions": tuple(map(str, data.get("institutions") or ())),
        "source_names": {str(k): str(v) for k, v in (data.get("source_names") or {}).items()},
        "derived_sources": tuple(map(str, data.get("derived_sources") or ())),
        "official_hosts": tuple(str(x).lower() for x in data.get("official_hosts") or ()),
        "url_patterns": tuple(map(str, data.get("url_patterns") or ())),
        "institution_hosts": {str(k).casefold(): tuple(str(h).lower() for h in v)
                              for k, v in (data.get("institution_hosts") or {}).items()},
        "public_source_domains": {str(k).casefold(): tuple(str(h).lower() for h in v)
                                  for k, v in (data.get("public_source_domains") or {}).items()},
        # Yerelde karşılığı olmayan, web'den çekilen dış kaynaklar. Anahtar '_note' meta; atlanır.
        "financial_sources": {
            str(k): {
                "aliases": tuple(str(a) for a in (spec.get("aliases") or ())),
                "hosts": tuple(str(h).lower() for h in (spec.get("hosts") or ())),
                "canonical_url": str(spec.get("canonical_url") or "") or None,
                "access_mode": str(spec.get("access_mode") or "") or None,
                "adapter_key": str(spec.get("adapter_key")) if spec.get("adapter_key") else None,
                # Otomatik erişim engellenirse kullanıcıya verilecek dışa aktarım yolu (ADR-0111); yoksa None.
                "name": str(spec.get("name") or "") or None,
                "manual_export": ({"url": str(spec["manual_export"].get("url") or "") or None,
                                   "steps": str(spec["manual_export"].get("steps") or "") or None}
                                  if isinstance(spec.get("manual_export"), dict) else None),
            }
            for k, spec in (data.get("financial_sources") or {}).items()
            if isinstance(spec, dict) and not str(k).startswith("_")
        },
    }


def load_source_hints() -> dict[str, Any]:
    return _load(os.getenv("SOURCE_HINTS_FILE") or str(DEFAULT_PATH))


def clear_cache() -> None:
    _load.cache_clear()


__all__ = ["DEFAULT_PATH", "clear_cache", "load_source_hints"]
