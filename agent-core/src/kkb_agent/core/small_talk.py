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


# ---------------------------------------------------------------- yetenek soruları ve dolgu (kullanıcı geri bildirimi, ADR-0078)
# "İnternetten araştırma yapabiliyor musun" sorusuna model "Anladım, not aldım. Ama elimde veri sorusu yok" dedi; "hangi veri setlerine
# sahipsin" sorusunda Gold'u anlattı. İkisi de sistemin kendi durumuyla deterministik cevaplanır: kayıtlı araçlar ve katalog.
_CAP_WEB = re.compile(r"(internet|web|çevrimiçi|cevrimici|online|google)\w*.{0,40}?(araştır|arastir|arama|arayabil|bakabil|bulabil|eriş|eris)", re.I)
_CAP_ASK = re.compile(r"m[ıiuü]s[ıiuü]n|yapabil|edebil|olur mu|mümkün mü|mumkun mu|\?", re.I)
_CAP_DATA = re.compile(
    r"(hangi|ne|neler)\s+(tür\s+|tur\s+)?(veri\w*(\s*set\w*|\s*kaynak\w*)?|kaynak\w*|seri\w*)\b.{0,30}?"
    r"(var|sahip|elinde|mevcut|kullan|bulun|yükl|yukl)|veri\s*set\w*\s+(ne|neler|hangi)", re.I)
_FILLER = re.compile(r"^\s*(?:(?:anladım|anladim|anlaşıldı|not aldım|not aldim|haklısın(?:ız)?|özür dilerim|ozur dilerim|"
                     r"kusura bakma(?:yın)?|affedersin(?:iz)?)\s*[,.!]?\s*)+", re.I)


def capability_reply(question: str, *, tools: set[str], datasets) -> str | None:
    """Yetenek ya da veri seti sorusu ise tek paragraf cevap; değilse None. Rakam geçen ya da uzun mesaj veri sorusudur."""
    text = (question or "").strip()
    if not text or re.search(r"\d", text) or len(text.split()) > 14:
        return None
    from ..source_hints import load_source_hints

    hints = load_source_hints()
    if _CAP_WEB.search(text) and _CAP_ASK.search(text):
        if "web_search" in tools:
            hosts = list(hints.get("official_hosts", ()))[:3]
            extra = f" Resmi kaynakların ({', '.join(hosts)} gibi) adreslerini kendim açabilirim." if hosts and "web_url" in tools else ""
            return ("Evet. İnternette arama yapıp bulduğum ya da senin verdiğin sayfaları, PDF'leri ve veri dosyalarını okuyabilir, "
                    "içlerindeki tabloyu analiz için alabilirim." + extra)
        if "web_url" in tools:
            return "Kısmen. Bu ortamda web araması kapalı; bir adres verirsen o sayfayı, PDF'i ya da veri dosyasını okuyabilirim."
        return "Hayır. Bu profilde internete erişen araçlar kapalı; yalnız veri havuzundaki serilerle çalışıyorum."
    if _CAP_DATA.search(text):
        return data_sets_reply(list(datasets()), hints)
    return None


def data_sets_reply(specs: list, hints: dict) -> str:
    """Birincil kaynaklara göre yüklü seriler (okunur ad, seri sayısı, kapsam); türetilmiş katmanlar kaynak sayılmaz."""
    names, derived = hints.get("source_names", {}), set(hints.get("derived_sources", ()))
    groups: dict[str, dict] = {}
    uploads = 0
    for spec in specs:
        src = getattr(spec, "source", "") or ""
        if src in derived:
            uploads += src == "adhoc"
            continue
        g = groups.setdefault(src, {"n": 0, "start": None, "end": None})
        g["n"] += 1
        cov = getattr(spec, "coverage", None)
        for key, value, pick in (("start", getattr(cov, "start", None), min), ("end", getattr(cov, "end", None), max)):
            if value is not None:
                g[key] = value if g[key] is None else pick(g[key], value)
    if not groups and not uploads:
        return "Veri havuzunda şu an yüklü seri yok."
    parts = []
    for src, g in sorted(groups.items(), key=lambda kv: -kv[1]["n"]):
        span = f" ({g['start']:%Y-%m} → {g['end']:%Y-%m})" if g["start"] and g["end"] else ""
        parts.append(f"{names.get(src, src)}: {g['n']} seri{span}")
    text = ("Veri havuzunda şu kaynaklardan yüklü seriler var: " + "; ".join(parts) + ".") if parts else ""
    if uploads:
        text += f" Kullanıcının eklediği {uploads} seri de var."
    return text.strip()


def strip_filler_opening(text: str) -> tuple[str, bool]:
    """Cevabın başındaki "Anladım, not aldım." / "Özür dilerim." dolgusunu kırpar; ardından gelen "Ama/Ancak" bağlacı da düşer."""
    m = _FILLER.match(text or "")
    if not m or m.end() == 0:
        return text, False
    rest = re.sub(r"^(?:ama|ancak|fakat)\s+", "", text[m.end():], flags=re.I).lstrip()
    if not rest:
        return text, False
    return rest[0].upper() + rest[1:], True

