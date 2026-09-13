"""Where the generic connector is allowed to read from, and where it is not.

Two separate problems live here.

**Local files.** The connector is handed a path by an agent that is, in turn, handed one by a
user. Neither is trusted. The boundary is an explicit allow-list of roots: a path is accepted
only if its fully resolved form is inside one of them. Resolving first is what makes ``..``
and symlinks safe, because both are gone by the time the comparison happens.

**URLs.** The connector must not become a way to read the machine it runs on, or the cloud
metadata service next to it. Every hostname is resolved and *every* address it resolves to is
checked, and the check is repeated for every redirect hop, because a redirect is a fresh
request to a fresh host.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final
from urllib.parse import urlsplit


ALLOWED_URL_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})
"""Only real network fetches. ``file://`` would bypass the local allow-list, ``ftp://`` and
the rest are simply not supported."""

DEFAULT_MAX_BYTES: Final[int] = 64 * 1024 * 1024
"""64 MiB. Large enough for a five-year bulletin export, small enough that a mistake does not
exhaust memory. Applied to local files and to streamed responses alike."""

DEFAULT_MAX_REDIRECTS: Final[int] = 3

_BLOCKED_HOST_SUFFIXES: Final[tuple[str, ...]] = (
    ".localhost",
    ".local",
    ".internal",
)

_CLOUD_METADATA_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)
"""Named cloud metadata endpoints. The address checks below already cover 169.254.169.254,
but a name that resolves through a split-horizon resolver may not look link-local."""


class AccessDeniedError(ValueError):
    """Raised when a target is reachable but reading it is not permitted."""


# ------------------------------------------------------------------ local files


@dataclass(frozen=True)
class LocalFilePolicy:
    """The rules a local path must satisfy before a single byte is read."""

    allowed_roots: tuple[Path, ...]
    max_bytes: int = DEFAULT_MAX_BYTES

    def __post_init__(self) -> None:
        if not self.allowed_roots:
            raise ValueError(
                "allowed_local_roots must not be empty; the generic connector never reads a "
                "local file without an explicit root"
            )
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        object.__setattr__(
            self,
            "allowed_roots",
            tuple(Path(root).expanduser().resolve(strict=True) for root in self.allowed_roots),
        )

        if any(not root.is_dir() for root in self.allowed_roots):
            raise ValueError("allowed_local_roots must contain directories, not files")


def resolve_local_file(path: str | Path, policy: LocalFilePolicy) -> Path:
    """Return the resolved path, or refuse.

    The checks, and what each one is actually for:

    - ``resolve()`` collapses ``..`` and follows every symlink, so the comparison below is
      against the real target rather than the string the caller typed.
    - The root check is done on the resolved parents, not with ``startswith``, so
      ``/data-evil`` is not accepted as being inside ``/data``.
    - Only a regular file is read. A directory, device, FIFO or socket either has no bytes to
      offer or would block forever, and ``/dev/zero`` would happily fill the size limit.
    - The size limit is checked before reading. This is a *guard*, not a guarantee: a file can
      grow between the check and the read, so the reader below enforces the limit again on the
      bytes it actually got. That second check is the one that holds.
    """

    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise AccessDeniedError(f"local path does not exist: {candidate}") from exc
    except OSError as exc:
        raise AccessDeniedError(f"local path could not be resolved: {candidate}") from exc

    if not any(
        resolved == root or root in resolved.parents for root in policy.allowed_roots
    ):
        # The message names the roots but not the resolved path: a traversal attempt should
        # not be told where it landed.
        raise AccessDeniedError(
            "local path resolves outside every allowed root "
            f"({[str(root) for root in policy.allowed_roots]})"
        )

    if not resolved.is_file():
        raise AccessDeniedError(
            f"only regular files are read; {resolved.name} is not one"
        )

    size = resolved.stat().st_size
    if size > policy.max_bytes:
        raise AccessDeniedError(
            f"local file is {size} bytes, over the {policy.max_bytes} byte limit"
        )
    return resolved


def read_local_file(path: str | Path, policy: LocalFilePolicy) -> tuple[Path, bytes]:
    """Read an allowed local file, enforcing the size limit on the bytes actually read.

    One extra byte is requested deliberately: if the file grew between ``stat`` and the read,
    that is how we find out, rather than silently truncating it to the limit.
    """

    resolved = resolve_local_file(path, policy)
    with resolved.open("rb") as handle:
        content = handle.read(policy.max_bytes + 1)
    if len(content) > policy.max_bytes:
        raise AccessDeniedError(
            f"local file exceeds the {policy.max_bytes} byte limit while being read"
        )
    return resolved, content


# -------------------------------------------------------------------------- URLs


def _address_is_blocked(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Return why an address is off-limits, or None when it is a normal public address."""

    # Unwrap IPv4-mapped IPv6 (::ffff:a.b.c.d) first. CPython 3.12 patch releases disagree on whether
    # such an address reports is_loopback or is_private (measured 14 Sep 2026: local 3.12.13 says
    # loopback, the GitHub runner's 3.12 said private), so the reason must not depend on the interpreter.
    mapped_first = getattr(address, "ipv4_mapped", None)
    if mapped_first is not None:
        address = mapped_first

    if address.is_loopback:
        return "loopback"
    if address.is_private:
        return "private"
    if address.is_link_local:
        return "link-local"
    if address.is_multicast:
        return "multicast"
    if address.is_reserved:
        return "reserved"
    if address.is_unspecified:
        return "unspecified"
    if getattr(address, "is_site_local", False):
        return "site-local"
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        reason = _address_is_blocked(mapped)
        if reason is not None:
            return f"IPv4-mapped {reason}"
    return None


def _resolve_all(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise AccessDeniedError(f"host {host!r} could not be resolved") from exc
    addresses = []
    for info in infos:
        try:
            addresses.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    if not addresses:
        raise AccessDeniedError(f"host {host!r} resolved to no usable address")
    return addresses


def assert_url_is_allowed(
    url: str, *, resolver: Callable[[str], list] | None = None
) -> None:
    """Refuse a URL that must not be fetched.

    Checked, in order: the scheme, embedded credentials, the literal hostname, and then
    **every** address the hostname resolves to. Checking every address matters because a name
    with both a public and a loopback record would otherwise pass on the strength of the
    public one and connect to the loopback one.

    **Known limitation, stated plainly:** this is a check at one moment in time. A resolver
    that returns a public address here and a private one when the HTTP client connects -- DNS
    rebinding -- is not prevented by this function, because the client does its own
    resolution. Closing that hole needs the connection to be pinned to the address that was
    validated, which this version does not do. Redirect hops are re-validated, so the common
    "public URL redirects to 169.254.169.254" case *is* covered; the residual risk is a
    hostile or compromised resolver.
    """

    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_URL_SCHEMES:
        raise AccessDeniedError(
            f"only {sorted(ALLOWED_URL_SCHEMES)} URLs are fetched, got {scheme or 'no'} scheme"
        )
    if parts.username or parts.password:
        # Credentials in a URL would end up in the stored locator and in logs.
        raise AccessDeniedError(
            "URL credentials (user:password@host) are refused; pass secrets in a header"
        )
    host = (parts.hostname or "").strip().lower()
    if not host:
        raise AccessDeniedError("URL has no host")
    if host in _CLOUD_METADATA_HOSTS or host == "localhost":
        raise AccessDeniedError(f"host {host!r} is blocked")
    if any(host.endswith(suffix) for suffix in _BLOCKED_HOST_SUFFIXES):
        raise AccessDeniedError(f"host {host!r} is blocked")

    resolve = resolver or _resolve_all
    for address in resolve(host):
        reason = _address_is_blocked(address)
        if reason is not None:
            raise AccessDeniedError(
                f"host {host!r} resolves to a {reason} address, which is blocked"
            )


__all__ = [
    "ALLOWED_URL_SCHEMES",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_REDIRECTS",
    "AccessDeniedError",
    "LocalFilePolicy",
    "assert_url_is_allowed",
    "read_local_file",
    "resolve_local_file",
]
