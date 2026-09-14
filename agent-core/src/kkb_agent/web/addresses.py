"""Adres güven sınırı — web getirme (`web.fetch`) ve dosya okuyucu (`builder.read`) aynı kuralı kullanır (M05-T03).

Lakehouse generic bağlayıcısıyla (`lakehouse.generic._access`) aynı kararı verir; ortak vakalar
`docs/sozlesmeler/url_erisim_vakalari.json` dosyasında, iki paketin testi de onu okur. Ölçüldü 14 Eyl:
ajan tarafı çoklu yayın (224.0.0.1), belirtilmemiş ve site-local adresleri geçiriyordu; IPv4-eşlemeli adresin
etiketi Python yamasına göre değişiyordu. Paket içinden hiçbir şey import etmez (döngüsel import yok).
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Callable, Iterable

BLOCKED_NAMES = frozenset({"localhost", "metadata.google.internal"})
BLOCKED_NAME_SUFFIXES = (".localhost", ".internal")

_RULES = (
    ("is_loopback", "loopback"), ("is_private", "private"), ("is_link_local", "link-local"),
    ("is_multicast", "multicast"), ("is_reserved", "reserved"), ("is_unspecified", "unspecified"),
    ("is_site_local", "site-local"),
)


def blocked_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Adres neden yasak (etiket) ya da None. IPv4-eşlemeli IPv6 önce açılır."""
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    for attr, reason in _RULES:
        if getattr(ip, attr, False):
            return reason
    return None


def _resolve(name: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    out = []
    for info in socket.getaddrinfo(name, None):
        out.append(ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]))
    return out


def blocked_host(host: str, *, resolver: Callable[[str], Iterable] | None = None) -> str | None:
    """Ad ya da adres yasaksa etiket. Çözülemeyen ad yasak sayılmaz (istek zaten başarısız olur)."""
    name = (host or "").strip().strip("[]").lower().rstrip(".")
    if not name:
        return None
    if name in BLOCKED_NAMES or name.endswith(BLOCKED_NAME_SUFFIXES):
        return "internal-name"
    try:
        return blocked_address(ipaddress.ip_address(name))
    except ValueError:
        pass
    try:
        addresses = list(resolver(name)) if resolver is not None else _resolve(name)
    except (OSError, UnicodeError, ValueError):
        return None
    for address in addresses:
        reason = blocked_address(address)
        if reason is not None:
            return reason
    return None


__all__ = ["BLOCKED_NAMES", "BLOCKED_NAME_SUFFIXES", "blocked_address", "blocked_host"]
