"""Grafik katmanı: Vega-Lite belirtimi VERİDİR, denetlenir; model eksen kararı vermez (ADR-0032).

Üç parça, üçü de LLM'siz:

- `spec.py`   — tablo + niyet → Vega-Lite v5 belirtimi. Kurallar inşa sırasında uygulanır:
                stok/akım için y=0, birim ve dönem başlıkta, kaynak uyarılı gözlem işaretli,
                çift eksen ve log yalnız istenirse ve etiketli.
- `lint.py`   — aynı belirtimi bağımsız olarak sınar. İnşacı hata yaparsa ya da bir gün
                model belirtimi kendi yazarsa, denetçi grafiği durdurur (fail-closed).
- `render.py` — belirtimi diske yazar; PNG/SVG `vl-convert` ile tarayıcısız üretilir.
"""

from .geo import GEO_FILENAME, load_geo_asset
from .lint import LintReport, RuleResult, lint_spec
from .render import ChartFiles, render_chart
from .spec import ChartIntent, GeoAsset, build_spec, normalize_province, period_label

__all__ = [
    "ChartFiles", "ChartIntent", "GEO_FILENAME", "GeoAsset", "LintReport", "RuleResult",
    "load_geo_asset",
    "build_spec", "lint_spec", "normalize_province", "period_label", "render_chart",
]
