"""Belirtimi diske yaz; PNG/SVG'yi tarayıcısız üret.

`vl-convert` Vega-Lite'ı yerel bir Rust çalışma zamanıyla çizer: ağ yok, tarayıcı yok,
Node yok. Kurulu değilse belirtim yine yazılır (`.vl.json`) ve karta "PNG üretilemedi"
düşer — grafik kaybolmaz, sadece görüntüsü sonra üretilir.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .spec import spec_json


@dataclass(frozen=True)
class ChartFiles:
    spec_path: Path
    png_path: Path | None
    svg_path: Path | None
    render_error: str | None = None

    def lines(self) -> list[str]:
        out = [f"belirtim: {self.spec_path}"]
        if self.png_path:
            out.append(f"png: {self.png_path}")
        if self.svg_path:
            out.append(f"svg: {self.svg_path}")
        if self.render_error:
            out.append(f"görüntü üretilemedi: {self.render_error}")
        return out


def _slug(text: str) -> str:
    tr = str.maketrans("çğıöşüÇĞİÖŞÜ ", "cgiosuCGIOSU_")
    s = re.sub(r"[^A-Za-z0-9_]+", "_", text.translate(tr)).strip("_").lower()
    return (s or "grafik")[:48]


def render_chart(spec: dict[str, Any], *, out_dir: Path, stem: str | None = None, scale: float = 2.0) -> ChartFiles:
    """Belirtimi ve görüntülerini yazar. Ad = başlık slug'ı + belirtim özeti (deterministik)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    text = spec_json(spec)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    title = spec.get("title", {})
    base = stem or _slug(title.get("text", "grafik") if isinstance(title, dict) else str(title))
    stem_full = f"{base}_{digest}"
    spec_path = out_dir / f"{stem_full}.vl.json"
    spec_path.write_text(text, encoding="utf-8")

    png_path = svg_path = None
    error = None
    try:
        import vl_convert as vlc  # type: ignore
    except ImportError:
        error = "vl-convert kurulu değil"
    else:
        try:
            png_path = out_dir / f"{stem_full}.png"
            png_path.write_bytes(vlc.vegalite_to_png(spec, scale=scale))
            svg_path = out_dir / f"{stem_full}.svg"
            svg_path.write_text(vlc.vegalite_to_svg(spec), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 — görüntü hatası belirtimi geçersiz kılmaz
            error = f"{type(exc).__name__}: {str(exc)[:200]}"
            png_path = png_path if png_path and png_path.exists() else None
            svg_path = svg_path if svg_path and svg_path.exists() else None
    return ChartFiles(spec_path=spec_path, png_path=png_path, svg_path=svg_path, render_error=error)


__all__ = ["ChartFiles", "render_chart"]
