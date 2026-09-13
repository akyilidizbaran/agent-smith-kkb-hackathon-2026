"""Selamlaşma ve istenmemiş öneri kuyruğu — harness kuralı, LLM'e iş yok (ADR-0045).

İki gözlem: (1) "selam" gibi veri sorusu olmayan bir mesajda model, elindeki analiz bağlamını
(aktif tablo, tarihçe, katalog kartları) "devam menüsü" olarak sunuyor: emoji, madde madde
öneriler, "Ne yapmak istersin?". (2) Gerçek sorularda da cevabın sonuna "Başka bir analiz
istersen…" kuyruğu ekliyor. Kullanıcının çizgisi: yalnız sorulana cevap.

Çözüm deterministik: selamlaşma sözlükten tanınır ve tek cümleyle karşılanır (LLM çağrısı yok,
tablo/kanıt paneli yok); cevap sonundaki öneri kuyruğu kırpılır. Sözlük dar tutulur: mesajın
TÜM sözcükleri sözlükten olmalı ve rakam geçmemeli; "selam, 2025 konut kredisi?" selam değildir.
"""

from __future__ import annotations

import re

_GREETING_WORDS = frozenset({
    "selam", "selamlar", "merhaba", "merhabalar", "sa", "selamun", "aleyküm", "aleykum", "günaydın",
    "gunaydin", "iyi", "akşamlar", "aksamlar", "günler", "gunler", "geceler", "sabahlar", "hey", "hi",
    "hello", "hola", "nasılsın", "nasilsin", "naber", "napıyorsun", "napiyorsun", "nasıl", "nasil",
    "gidiyor", "teşekkürler", "tesekkurler", "teşekkür", "tesekkur", "ederim", "sağ", "sag", "ol", "olun",
    "eyvallah", "thanks", "thank", "you", "tamam", "tamamdır", "tamamdir", "ok", "okey", "peki",
    "harika", "süper", "super", "güzel", "guzel", "mükemmel", "mukemmel", "hoşça", "hosca", "kal",
    "görüşürüz", "gorusuruz", "bye", "test", "deneme", "ben", "kardeşim", "kardesim", "dostum", "abi",
    "kral", "hocam", "canım", "canim", "çok", "cok", "ya", "be", "efendim", "evet", "hayır", "hayir", "yok",
})
_TOKEN = re.compile(r"[a-zçğıöşüâîû]+", re.I)
_QUESTION_HINT = re.compile(r"\d|%|\?.*\w|tablo|grafik|veri|seri|dönem|donem|yıl|ay\b|hesapla|göster|goster|ekle|analiz|dosya|kaynak", re.I)


def is_small_talk(question: str) -> bool:
    """Mesaj yalnız selamlaşma/teşekkür/onay sözcüklerinden mi oluşuyor?"""
    text = question.strip()
    if not text or _QUESTION_HINT.search(text):
        return False
    words = [w.lower().replace("i̇", "i") for w in _TOKEN.findall(text)]
    if not words or len(words) > 6:
        return False
    return all(w in _GREETING_WORDS for w in words)


def small_talk_reply(question: str, *, has_table: bool) -> str:
    """Tek cümle; analiz anlatmaz, öneri listelemez."""
    low = question.lower()
    if any(w in low for w in ("teşekkür", "tesekkur", "sağ ol", "sag ol", "eyvallah", "thanks", "thank")):
        return "Rica ederim."
    if any(w in low for w in ("görüşürüz", "gorusuruz", "hoşça", "hosca", "bye")):
        return "Görüşmek üzere."
    if any(w in low for w in ("tamam", "ok", "peki", "harika", "süper", "super", "güzel", "guzel", "mükemmel", "evet")):
        return "Tamam."
    tail = " Aktif tablo duruyor; üzerinde devam edebilirsin." if has_table else ""
    return "Selam. Sorunu yazabilirsin." + tail


# Cevap sonundaki öneri kuyruğu: bu satırla başlayan paragraf ve sonrası düşer.
_OFFER_OPENER = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:\*\*)?(?:"
    r"başka bir (?:soru|analiz|şey|konu|istek|kalem|dönem)|başka (?:bir )?(?:şey|soru|analiz)|"
    r"istersen|isterseniz|dilersen|dilerseniz|ne yapmak isters|ne yapmak isterdin|"
    r"yardımcı olabileceğim|yardımcı olmamı ister|devam etmek isters|sonraki adım(?:lar)? (?:olarak|için)|"
    r"bir sonraki adımda|şunları da yapabilir|şunları yapabilir|ayrıca şunlar|örneğin\s*:?\s*$|"
    r"bunlardan (?:biri|hangisi)|hangisini isters|nasıl devam|ek olarak (?:istersen|şunlar)|"
    r"öneri(?:ler|m)?\s*:?\s*$|önerilen (?:sonraki )?adımlar|ilgini çekebilecek|ilginizi çekebilecek"
    r")",
    re.I | re.M,
)
_GREETING_LINE = re.compile(r"^\s*(?:selam|merhaba|hey|hello|hi)\b[^\n]{0,40}$", re.I | re.M)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⭕\U0001F000-\U0001F2FF]")


def trim_unsolicited_offers(text: str) -> tuple[str, bool]:
    """Cevabın sonundaki 'başka ne yapabilirim' kuyruğunu kırpar.

    Yalnız kuyruk: kesme noktasından ÖNCE anlamlı içerik yoksa (cevap tümüyle öneri) dokunmaz;
    o zaman sorun cevabın kendisidir, kırpmak boş cevap bırakır. Emoji her yerde kaldırılır.
    """
    if not text:
        return text, False
    original = text
    text = _EMOJI.sub("", text)
    paragraphs = re.split(r"\n\s*\n", text.strip())
    cut = None
    for idx, para in enumerate(paragraphs):
        first_line = para.strip().splitlines()[0] if para.strip() else ""
        if _OFFER_OPENER.match(first_line):
            cut = idx
            break
    if cut is not None and cut > 0:
        kept = "\n\n".join(paragraphs[:cut]).rstrip()
        # Kesilen paragrafın hemen öncesi de bir açılış cümlesiyse ("Selam!") onu bırakma.
        if kept.strip() and not _GREETING_LINE.fullmatch(kept.strip()):
            return kept, True
    text = text.strip()
    return text, text != original.strip()


__all__ = ["is_small_talk", "small_talk_reply", "trim_unsolicited_offers"]
