"""Varsayılan HTTP oturumu — httpx üzerinde, `requests` benzeri dar yüzey.

Ölçüldü: gerçek bir adrese ilk çıkışta `ModuleNotFoundError: requests` — sahte oturumla
geçen testler bu yolu hiç açmamıştı. Projede httpx var, requests yok; TLS için OS
sertifika deposu (`truststore`) kullanılır, `verify=False` asla.

Yüzey: `get(url, timeout, allow_redirects, stream, headers)` → `status_code`, `url`,
`headers`, `content`, `iter_content(n)`, `close()`; `post(url, json, timeout)` → `status_code`,
`json()`. Testler aynı yüzeyi sahteyle karşılar.
"""

from __future__ import annotations

import ssl
from typing import Any, Iterator

import httpx


class _Response:
    def __init__(self, resp: httpx.Response, *, stream: bool) -> None:
        self._resp = resp
        self._stream = stream
        self.status_code = resp.status_code
        self.url = str(resp.url)
        self.headers = dict(resp.headers)

    @property
    def content(self) -> bytes:
        if self._stream:
            self._resp.read()
        return self._resp.content

    def iter_content(self, chunk_size: int = 65536) -> Iterator[bytes]:
        if self._stream:
            yield from self._resp.iter_bytes(chunk_size)
        else:
            yield self._resp.content

    def json(self) -> Any:
        return self._resp.json()

    def close(self) -> None:
        self._resp.close()


class HttpxSession:
    def __init__(self, *, timeout: float = 30.0) -> None:
        verify: Any = True
        try:
            import truststore  # OS sertifika deposu: kurum sitelerinde ara sertifika sorunları için
            verify = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except Exception:  # noqa: BLE001
            verify = True
        self._client = httpx.Client(timeout=timeout, verify=verify, follow_redirects=True)

    def get(self, url: str, *, timeout: float | None = None, allow_redirects: bool = True,
            stream: bool = False, headers: dict[str, str] | None = None) -> _Response:
        if stream:
            req = self._client.build_request("GET", url, headers=headers, timeout=timeout)
            resp = self._client.send(req, stream=True, follow_redirects=allow_redirects)
            return _Response(resp, stream=True)
        resp = self._client.get(url, headers=headers, timeout=timeout, follow_redirects=allow_redirects)
        return _Response(resp, stream=False)

    def post(self, url: str, *, json: Any = None, timeout: float | None = None,
             headers: dict[str, str] | None = None) -> _Response:
        resp = self._client.post(url, json=json, timeout=timeout, headers=headers)
        return _Response(resp, stream=False)

    def close(self) -> None:
        self._client.close()


_DEFAULT: HttpxSession | None = None


def default_session() -> HttpxSession:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = HttpxSession()
    return _DEFAULT


__all__ = ["HttpxSession", "default_session"]
