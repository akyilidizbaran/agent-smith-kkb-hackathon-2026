"""İşlem kapsamlı onay (D03, ADR-0068): kalıcı yazma onayı bekleyen işleme ve GÜNCEL kullanıcı mesajına bağlıdır.

Önce promote kapısı birikmiş bütün sohbet metninde "onaylıyorum" + seri adını arıyordu: "sicaklik taslağını onaylıyorum"
bir tur önce yazılmışsa "Şimdi sicaklik yayınlama." bile terfiye yetiyordu (bağımsız kontrol R03). Kural artık:

- Bekleyen işlem (`PendingOp`): hedef seri, işlem türü, kullanıcıya gösterilen kapsam özeti ve gösterildiği tur.
  Taslak eklenince ya da onaysız terfi denemesi reddedilince kaydedilir.
- Karar YALNIZ bu turun kullanıcı mesajıyla verilir; geçmişteki onay yetki üretmez.
- Güncel ret/iptal ("yayınlama", "vazgeç", "hayır", "onaylamıyorum") her zaman kazanır ve bekleyen işlemi kapatır.
- Mesaj onay ifadesi + hedef seriyi birlikte taşıyorsa yalnız o işlem onaylıdır; başka bir seri adı geçiyorsa ret/netleştirme.
- Kısa "evet / onaylıyorum" yalnız ÖNCEKİ bir turda gösterilmiş TEK bekleyen işlem varsa geçerlidir; birden çoksa sorulur.
- Onay denemede tüketilir: başarısız işlem yeniden onay ister; başarılı işlem bekleyeni kapatır. İdempotent ikinci çağrı
  başka bir işleme onay sayılmaz.
- Dış içerik (web/dosya) kullanıcı mesajı değildir; bekleyen işlemi ve kararı değiştiremez. Oturum/profil değişince
  kayıt defteri yeniden kurulduğu için bekleyen işlemler de düşer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_APPROVE = re.compile(
    r"\b(onayl[ıi]yorum|onayla|onaylayal[ıi]m|onayl[ıi]yoruz|kataloğa al|kataloga al|terfi ettir|yayınla|yayinla|"
    r"silver'?a al|aktif et|evet|tamam|olur|devam et)\b", re.I,
)
_REJECT = re.compile(
    r"\b(yayınlama|yayinlama|onaylam[ıi]yorum|onaylama|reddediyorum|reddet|vazgeç\w*|vazgec\w*|iptal\w*|hayır|hayir|"
    r"istemiyorum|alma|yapma|dur|bekle|şimdilik değil|simdilik degil)\b", re.I,
)
_SHORT = re.compile(r"^\W*(evet|tamam|olur|onayl[ıi]yorum|onayla|kabul|devam et)\W*(,?\s*\w+){0,3}\W*$", re.I)


@dataclass
class PendingOp:
    series_id: str
    operation: str               # "promote"
    summary: str                 # kullanıcıya gösterilen kapsam özeti
    shown_turn: int


@dataclass
class ApprovalBook:
    pending: dict[str, PendingOp] = field(default_factory=dict)   # anahtar: "<işlem>:<seri>"

    def register(self, op: PendingOp) -> None:
        self.pending[f"{op.operation}:{op.series_id}"] = op

    def discard(self, operation: str, series_id: str) -> None:
        self.pending.pop(f"{operation}:{series_id}", None)

    def of(self, operation: str) -> list[PendingOp]:
        return [p for p in self.pending.values() if p.operation == operation]


# Arayüz yüklemesi dosyaya 8 onaltılık karakterlik ön ek koyar (web_app.save_upload: "cb6d79f3_hastane.csv"); model seri
# anahtarı vermeyince kimlik bu adla oluşur ("adhoc:cb6d79f3_hastane"). Kullanıcı ön eki görmez, "hastane taslağını
# onaylıyorum" der (canlı ölçüm, 15 Eyl: onay iki denemede de reddedildi). Ön eksiz ad da aynı hedeftir; onay sözü ve hedef
# yine aynı güncel mesajda olmalı.
_UPLOAD_PREFIX = re.compile(r"^[0-9a-f]{8}_(?=\w)")


def _mentions(text: str, series_id: str) -> bool:
    low = (text or "").casefold()
    key = series_id.split(":", 1)[-1].casefold()
    keys = {key, _UPLOAD_PREFIX.sub("", key)}
    return series_id.casefold() in low or any(re.search(rf"(?<![\w]){re.escape(k)}(?![\w])", low) for k in keys if k)


@dataclass(frozen=True)
class Decision:
    ok: bool
    reason: str = ""             # ret sebebi (kullanıcıya/modele)
    ask: bool = False            # netleştirme gerekiyor


def decide(book: ApprovalBook, *, operation: str, series_id: str, message: str, turn: int,
           known_targets: list[str] | None = None) -> Decision:
    """Bu turun mesajı bu işlemi onaylıyor mu? Geçmiş metin bilinçli olarak parametre değildir."""
    text = message or ""
    if _REJECT.search(text):
        book.discard(operation, series_id)
        return Decision(False, "Kullanıcının güncel mesajı bu işlemi reddediyor ya da iptal ediyor; işlem yapılmadı.")
    if not _APPROVE.search(text):
        return Decision(False, "Kullanıcının güncel mesajında bu işlem için onay yok; eski onaylar yetki sayılmaz.", ask=True)
    others = [t for t in (known_targets or []) if t != series_id and _mentions(text, t)]
    if _mentions(text, series_id):
        if others:
            return Decision(False, f"Mesaj birden çok hedef adlandırıyor ({series_id}, {', '.join(others)}); hangisi onaylandı sorulmalı.", ask=True)
        return Decision(True)
    if others:
        return Decision(False, f"Onay başka bir hedef için ({', '.join(others)}); '{series_id}' onaylanmadı.", ask=True)
    earlier = [p for p in book.of(operation) if p.shown_turn < turn]
    if _SHORT.search(text.strip()) and len(earlier) == 1 and earlier[0].series_id == series_id:
        return Decision(True)
    if _SHORT.search(text.strip()) and len(earlier) > 1:
        return Decision(False, "Onay bekleyen birden çok işlem var: " + ", ".join(p.series_id for p in earlier)
                        + "; hangisinin onaylandığı sorulmalı.", ask=True)
    return Decision(False, f"Kullanıcı hangi işlemi onayladığını söylemedi ('{series_id}' güncel mesajda geçmiyor ve "
                           "önceki turda gösterilmiş tek bekleyen işlem yok).", ask=True)


def book_of(registry: object) -> ApprovalBook:
    book = getattr(registry, "approvals", None)
    if book is None:
        book = ApprovalBook()
        try:
            setattr(registry, "approvals", book)
        except Exception:  # noqa: BLE001
            pass
    return book


__all__ = ["ApprovalBook", "Decision", "PendingOp", "book_of", "decide"]
