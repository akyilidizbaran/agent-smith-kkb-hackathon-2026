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
# Sözcük sınırı zorunlu (K01 bulgusu, 14 Eyl): "web_ziyaret serisinde davranış ne zaman değişti?" analiz sorusu "web" + "serisinde"
# içindeki "eris" ile yetenek sorusu sanılıp modele gitmeden cevaplandı.
_CAP_WEB = re.compile(r"(?<![\w])(internet\w*|web(?:'?(?:de|den|te|ten))?|çevrimiçi|cevrimici|online|google)(?![\w])"
                      r".{0,40}?(?<![\w])(araştır|arastir|arama|ara(?:r|yabil)|bakabil|bulabil|eriş|eris)\w*", re.I)
_CAP_ASK = re.compile(r"m[ıiuü]s[ıiuü]n|yapabil|edebil|olur mu|mümkün mü|mumkun mu|\?", re.I)
_CAP_DATA = re.compile(
    r"(?<![\w])(hangi|ne|neler)\s+(tür\s+|tur\s+)?(veri\w*(\s*set\w*|\s*kaynak\w*)?|kaynak\w*|seri\w*)\b.{0,30}?"
    r"(var|sahip|elinde|mevcut|kullan|bulun|yükl|yukl)|veri\s*set\w*\s+(ne|neler|hangi)", re.I)
# Analiz sözcüğü taşıyan mesaj yetenek sorusu değildir ("Hangi seride kırılma var?", "web_ziyaret serisinde davranış ne zaman değişti?").
_ANALYTIC = re.compile(r"kırılma|kirilma|aykırı|aykiri|anomali|artış|artis|arttı|artti|düşüş|dusus|düştü|dustu|azal|yüksel|yuksel|değiş|degis|"
                       r"trend|eğilim|egilim|fark|oran|toplam|ortalama|karşılaştır|karsilastir|grafik|tablo|davranış|davranis|rejim|öncü|oncu", re.I)
_FILLER = re.compile(r"^\s*(?:(?:anladım|anladim|anlaşıldı|not aldım|not aldim|haklısın(?:ız)?|özür dilerim|ozur dilerim|"
                     r"kusura bakma(?:yın)?|affedersin(?:iz)?)\s*[,.!]?\s*)+", re.I)


# İkinci tekil şart: "Faiz düşerse kredi ne yapabilir?" veri sorusudur, kimlik sorusu değil.
_IDENTITY = re.compile(r"(?<![\w])(kimsin(?:iz)?|sen\s+nesin|kendini(?:zi)?\s+tanıt\w*|kendin(?:iz)?den\s+bahset\w*|"
                       r"ne(?:ler)?\s+yapabilirsin(?:iz)?|ne\s+işe\s+yar(?:arsın|ıyorsun)\w*|nasıl\s+çalışıyorsun(?:uz)?|adın\s+ne)(?![\w])", re.I)


def is_identity_question(question: str) -> bool:
    """"Sen kimsin?", "Neler yapabilirsin?" gibi kısa kimlik/tanıtım sorusu mu? Veri çekmesi gerekmez.

    Kimlik deneyi (15 Eyl, docs/experiments/kimlik_alan_deneyi_2026-09-15_1546.json): aktif tablo yokken ajan bu soruyu
    "veri çekilmeden cevap denendi" diye geri gönderiyor, doğru ilk taslak "önceki mesajın 'Sen kimsin?' idi" diye bozuluyordu;
    tek kullanıcı serili DB'de model kimlik yerine tablo döküyordu. Rakamlı ya da uzun mesaj veri sorusudur."""
    text = (question or "").strip()
    return bool(text) and not re.search(r"\d", text) and len(text.split()) <= 8 and bool(_IDENTITY.search(text))


def capability_reply(question: str, *, tools: set[str], datasets) -> str | None:
    """Yetenek ya da veri seti sorusu ise tek paragraf cevap; değilse None. Rakam geçen ya da uzun mesaj veri sorusudur."""
    text = (question or "").strip()
    if not text or re.search(r"\d", text) or len(text.split()) > 14 or _ANALYTIC.search(text):
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
    from ..domain import series_label

    names, derived = hints.get("source_names", {}), set(hints.get("derived_sources", ()))
    groups: dict[str, dict] = {}
    uploads: list[str] = []
    for spec in specs:
        src = getattr(spec, "source", "") or ""
        if src in derived:
            if src == "adhoc":   # kimlik deneyi (15 Eyl): "Kullanıcının eklediği 1 seri de var." yarım cümleydi, seri adı yoktu
                cov = getattr(spec, "coverage", None)
                uploads.append(series_label(spec) + _span(getattr(cov, "start", None), getattr(cov, "end", None)))
            continue
        g = groups.setdefault(src, {"n": 0, "start": None, "end": None})
        g["n"] += 1
        cov = getattr(spec, "coverage", None)
        for key, value, pick in (("start", getattr(cov, "start", None), min), ("end", getattr(cov, "end", None), max)):
            if value is not None:
                g[key] = value if g[key] is None else pick(g[key], value)
    if not groups and not uploads:
        return "Veri havuzunda şu an yüklü seri yok."
    parts = [f"{names.get(src, src)}: {g['n']} seri{_span(g['start'], g['end'])}"
             for src, g in sorted(groups.items(), key=lambda kv: -kv[1]["n"])]
    text = ("Veri havuzunda şu kaynaklardan yüklü seriler var: " + "; ".join(parts) + ".") if parts else ""
    if uploads:
        listed = ", ".join(uploads[:5]) + (f" ve {len(uploads) - 5} seri daha" if len(uploads) > 5 else "")
        text += (f" Kullanıcının eklediği seriler: {listed}." if parts else f"Veri havuzunda kullanıcının eklediği seriler var: {listed}.")
    return text.strip()


def _span(start, end) -> str:
    """' (2025-01 → 2025-12)'; kapsam bilinmiyorsa (adaptörün 1900 yer tutucusu) boş."""
    if not start or not end or getattr(start, "year", 1900) <= 1900:
        return ""
    return f" ({start:%Y-%m} → {end:%Y-%m})"


def strip_filler_opening(text: str) -> tuple[str, bool]:
    """Cevabın başındaki "Anladım, not aldım." / "Özür dilerim." dolgusunu kırpar; ardından gelen "Ama/Ancak" bağlacı da düşer."""
    m = _FILLER.match(text or "")
    if not m or m.end() == 0:
        return text, False
    rest = re.sub(r"^(?:ama|ancak|fakat)\s+", "", text[m.end():], flags=re.I).lstrip()
    if not rest:
        return text, False
    return rest[0].upper() + rest[1:], True

