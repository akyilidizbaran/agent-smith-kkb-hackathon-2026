"""Niyet kapısı — yazma ve dışarı çıkma yeteneği olan araçlar için deterministik denetim (ADR-0037).

Architect ile Analist aynı modeldir ama aynı yetkiye sahip değildir; bu dosya son halkayı
kodlar: **kaynak yalnız kullanıcının kendi mesajından gelebilir**, araç çıktısından gelemez.
Bir web sayfasına ya da dosyaya gömülü "şu adresi ingest et" cümlesi model için veridir;
küçük model bunu talimat sansa bile adres kullanıcı mesajında yoksa kapı kapalıdır.

İki kontrol, ikisi de LLM'siz:
- `locator_from_user`: adres (URL ya da dosya adı) kullanıcı metninde geçiyor mu, ya da
  kullanıcının istediği bir aramanın sonuçlarında mı (onaylı adresler)?
- `write_intent`: kullanıcı metninde yazma niyeti var mı (ekle, yükle, kaydet, ingest …)?
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

_WRITE = re.compile(
    r"\b(ekle|ekler misin|ekleyelim|yükle|yükler misin|yükleyelim|kaydet|kaydedelim|ingest|"
    r"havuza|içe aktar|aktar|taslak (?:seri )?olarak)\b",
    re.I,
)


def _norm_url(url: str) -> str:
    p = urlparse(url.strip())
    return f"{p.scheme.lower()}://{p.netloc.lower()}{p.path.rstrip('/')}"


def locator_from_user(locator: str, user_text: str, sanctioned: Iterable[str] = ()) -> bool:
    """Adres kullanıcıdan mı? URL: aynı adres (sondaki '/' ve sorgu dizesi hariç) kullanıcı
    metninde ya da onaylı listede. Yerel dosya: dosya adı kullanıcı metninde."""
    text = user_text or ""
    if not locator:
        return False
    parsed = urlparse(locator)
    if parsed.scheme in ("http", "https"):
        want = _norm_url(locator)
        for m in re.finditer(r"https?://[^\s<>\"'\)]+", text, re.I):
            if _norm_url(m.group(0)) == want:
                return True
        return any(_norm_url(s) == want for s in sanctioned)
    name = Path(parsed.path if parsed.scheme == "file" else locator).name
    return bool(name) and name in text


def write_intent(user_text: str) -> bool:
    return bool(_WRITE.search(user_text or ""))


__all__ = ["locator_from_user", "write_intent"]
