"""İl sınırlarını (GeoJSON) yükler. Dosya yoksa harita yok; uydurulmaz.

Beklenen dosya: `<geo_dir>/tr_provinces.geojson` — FeatureCollection, her feature'da il adı
taşıyan bir özellik (`name`, `NAME_1`, `il`, `ad`, `province` ...). Kaynağı ve lisansı
`<geo_dir>/README.md`'de yazılı olmalı; karta dosya yolu yazılır.
"""

from __future__ import annotations

import json
from pathlib import Path

from .spec import GeoAsset

GEO_FILENAME = "tr_provinces.geojson"
_NAME_PROPERTIES = ("name", "NAME", "NAME_1", "il", "il_adi", "ad", "province", "adm1_name", "ILADI")


def load_geo_asset(geo_dir: Path | None, *, filename: str = GEO_FILENAME) -> GeoAsset | None:
    if geo_dir is None:
        return None
    path = Path(geo_dir) / filename
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    features = document.get("features") if isinstance(document, dict) else None
    if not features:
        return None
    props = features[0].get("properties", {}) or {}
    name_property = next((k for k in _NAME_PROPERTIES if k in props), None)
    if name_property is None:
        return None
    return GeoAsset(features=tuple(features), name_property=name_property, source=str(path))


__all__ = ["GEO_FILENAME", "load_geo_asset"]
