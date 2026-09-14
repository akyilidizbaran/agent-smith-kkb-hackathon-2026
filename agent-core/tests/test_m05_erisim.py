"""M05 (ADR-0051): yönlendirme hedefi istekten ÖNCE doğrulanır; robots aynı sınırdan; döngü, sekme,
yarım indirme ve DNS hatası kontrollü. Gerçek özel servise istek yapılmaz: sahte taşıma."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.web.fetch import FetchRefused, RedirectRefused, RobotsCache, fetch_url, guarded_get  # noqa: E402


class Resp:
    def __init__(self, status, body=b"", headers=None, url=None, broken=False):
        self.status_code, self._body, self.headers, self.url, self.broken = status, body, headers or {}, url, broken
        self.closed = False

    @property
    def content(self):
        return self._body

    def iter_content(self, n=65536):
        if self.broken:
            raise ConnectionError("bağlantı koptu")
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]

    def close(self):
        self.closed = True


class Transport:
    """URL → yanıt; her isteği kaydeder. Otomatik yönlendirme YOK: istenirse hata."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, *, allow_redirects=True, **kw):
        assert allow_redirects is False, "kütüphane yönlendirmesi kapalı olmalı"
        self.calls.append((url, kw.get("headers") or {}))
        r = self.routes.get(url)
        if r is None:
            return Resp(404, b"yok")
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(autouse=True)
def _privates(monkeypatch):
    # DNS yok: yalnız açık özel adresler özel sayılır
    monkeypatch.setattr("kkb_agent.web.fetch.private_host", lambda h: h in {"127.0.0.1", "localhost", "10.0.0.5", "169.254.169.254"})


def test_a19_public_to_private_redirect_hedefe_gitmeden_reddedilir():
    t = Transport({"https://public.test/veri": Resp(302, headers={"Location": "http://127.0.0.1:9999/private"})})
    with pytest.raises(RedirectRefused, match="özel/loopback"):
        fetch_url("https://public.test/veri", session=t)
    assert [u for u, _ in t.calls] == ["https://public.test/veri"], "özel adrese istek yapılmadı"


def test_public_to_public_redirect_takip_edilir_ve_son_url_kaydedilir():
    t = Transport({"https://public.test/eski": Resp(301, headers={"Location": "/yeni.csv"}),
                   "https://public.test/yeni.csv": Resp(200, b"a;b\n1;2\n", headers={"Content-Type": "text/csv"})})
    r = fetch_url("https://public.test/eski", session=t)
    assert r.ok and r.final_url == "https://public.test/yeni.csv" and r.content.startswith(b"a;b") and r.is_data_file


def test_redirect_dongusu_ve_sekme_siniri():
    t = Transport({"https://a.test/1": Resp(302, headers={"Location": "https://a.test/2"}),
                   "https://a.test/2": Resp(302, headers={"Location": "https://a.test/1"})})
    with pytest.raises(RedirectRefused, match="döngü"):
        fetch_url("https://a.test/1", session=t)
    chain = {f"https://b.test/{i}": Resp(302, headers={"Location": f"https://b.test/{i + 1}"}) for i in range(10)}
    with pytest.raises(RedirectRefused, match="yönlendirmeden sonra"):
        fetch_url("https://b.test/0", session=Transport(chain))


def test_robots_yonlendirmesi_ozel_adrese_gitmez_ve_ana_istek_yine_calisir():
    t = Transport({"https://c.test/robots.txt": Resp(302, headers={"Location": "http://10.0.0.5/robots.txt"}),
                   "https://c.test/veri": Resp(200, b"<html>ok</html>", headers={"Content-Type": "text/html"})})
    robots = RobotsCache()
    r = fetch_url("https://c.test/veri", session=t, robots=robots)
    assert r.ok and "https://c.test" in robots.unreachable_hosts
    assert all(not u.startswith("http://10.0.0.5") for u, _ in t.calls)


def test_dns_hatasi_ve_yarim_indirme_kontrollu():
    t = Transport({"https://d.test/x": OSError("dns yok")})
    r = fetch_url("https://d.test/x", session=t)
    assert not r.ok and r.http_status is None and r.content == b""
    broken = Resp(200, b"x" * 10, headers={"Content-Type": "text/csv"}, broken=True)
    r2 = fetch_url("https://e.test/x", session=Transport({"https://e.test/x": broken}))
    assert not r2.ok and r2.content == b"" and broken.closed, "yarım indirmede bağlantı kapanır, sahte başarı yok"


def test_byte_siniri_ve_baska_hosta_baslik_tasinmaz():
    big = Resp(200, b"x" * 2000, headers={"Content-Type": "text/csv"})
    with pytest.raises(FetchRefused, match="bayt"):
        fetch_url("https://f.test/big", session=Transport({"https://f.test/big": big}), max_bytes=1000)
    assert big.closed
    t = Transport({"https://g.test/a": Resp(302, headers={"Location": "https://h.test/b"}), "https://h.test/b": Resp(200, b"ok")})
    guarded_get(t, "https://g.test/a", timeout=5, headers={"User-Agent": "ua", "Accept": "*/*", "Authorization": "Bearer gizli"})
    first, second = t.calls
    assert "Authorization" in first[1] and "Authorization" not in second[1]
