"""Shared synthetic catalog for experiments E8 (catalog-in-prompt threshold) and the retrieval bake-off.

Two layers:
  * ~60 realistic Turkish financial series (BDDK/EVDS-like) with hand-written aliases — these are
    the evaluation targets and carry hand-written test queries (exact, abbreviation, synonym, English,
    typo, misleading neighbour).
  * Synthetic filler series generated from templates to reach N = 50 / 200 / 1000 / 3000.

No real EVDS/BDDK codes are asserted; ids are namespaced `syn:` to make that explicit.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class Series:
    series_id: str
    name_tr: str
    unit: str
    frequency: str
    measure_type: str
    aliases: list[str] = field(default_factory=list)
    category: str = ""

    def doc(self) -> str:
        """Text used for BM25/embedding and for the catalog line in the prompt."""
        al = ", ".join(self.aliases)
        return f"{self.series_id} | {self.name_tr} | {self.unit} | {self.frequency} | {self.measure_type} | {al} | {self.category}"

    def prompt_line(self) -> str:
        return f"{self.series_id}: {self.name_tr} [{self.unit}, {self.frequency}, {self.measure_type}]"


REAL: list[Series] = [
    Series("syn:bddk:konut_kredi_bakiye", "Konut kredileri bakiyesi (sektör, TL)", "TRY_mn", "monthly", "stock",
           ["mortgage bakiyesi", "ev kredisi", "konut kredisi tutarı", "konut kredisi stoku", "housing loans"], "krediler/tüketici"),
    Series("syn:evds:konut_kredi_faiz", "Konut kredisi faiz oranı (TL, ağırlıklı ortalama, akım)", "pct", "weekly", "rate",
           ["mortgage faizi", "ev kredisi faizi", "konut faiz oranı", "housing loan interest rate"], "faiz/kredi"),
    Series("syn:evds:kfe", "Konut fiyat endeksi (KFE, 2023=100)", "index", "monthly", "index",
           ["KFE", "ev fiyatları", "konut fiyatları", "house price index", "konut fiyat endeksi"], "reel sektör/konut"),
    Series("syn:evds:tufe", "Tüketici fiyat endeksi (TÜFE, 2003=100)", "index", "monthly", "index",
           ["TÜFE", "enflasyon endeksi", "CPI", "tüketici enflasyonu", "fiyat endeksi"], "fiyatlar"),
    Series("syn:evds:ufe", "Yurt içi üretici fiyat endeksi (Yİ-ÜFE)", "index", "monthly", "index",
           ["ÜFE", "üretici fiyatları", "PPI", "üretici enflasyonu"], "fiyatlar"),
    Series("syn:evds:politika_faizi", "TCMB politika faizi (bir hafta vadeli repo)", "pct", "daily", "rate",
           ["politika faizi", "repo faizi", "merkez bankası faizi", "policy rate", "PPK faizi"], "faiz/politika"),
    Series("syn:bddk:tuketici_kredi_bakiye", "Tüketici kredileri bakiyesi (konut+taşıt+ihtiyaç)", "TRY_mn", "monthly", "stock",
           ["bireysel krediler", "tüketici kredisi toplamı", "consumer loans"], "krediler/tüketici"),
    Series("syn:bddk:tasit_kredi_bakiye", "Taşıt kredileri bakiyesi", "TRY_mn", "monthly", "stock",
           ["araba kredisi", "oto kredisi", "araç kredisi", "vehicle loans"], "krediler/tüketici"),
    Series("syn:bddk:ihtiyac_kredi_bakiye", "İhtiyaç kredileri bakiyesi", "TRY_mn", "monthly", "stock",
           ["ihtiyaç kredisi", "genel amaçlı kredi", "general purpose loans", "nakit kredi"], "krediler/tüketici"),
    Series("syn:bddk:kobi_kredi_bakiye", "KOBİ kredileri bakiyesi", "TRY_mn", "monthly", "stock",
           ["KOBİ kredisi", "küçük işletme kredisi", "SME loans"], "krediler/ticari"),
    Series("syn:bddk:ticari_kredi_bakiye", "Ticari ve kurumsal krediler bakiyesi", "TRY_mn", "monthly", "stock",
           ["ticari kredi", "kurumsal kredi", "commercial loans", "firma kredileri"], "krediler/ticari"),
    Series("syn:bddk:kredi_karti_bakiye", "Bireysel kredi kartı alacakları", "TRY_mn", "monthly", "stock",
           ["kredi kartı borcu", "kart alacakları", "credit card receivables", "kredi kartı bakiyesi"], "krediler/tüketici"),
    Series("syn:bddk:takipteki_alacak", "Takipteki alacaklar (brüt)", "TRY_mn", "monthly", "stock",
           ["NPL", "batık kredi", "donuk alacak", "tahsili gecikmiş alacak", "non-performing loans"], "aktif kalitesi"),
    Series("syn:bddk:npl_orani", "Takipteki alacaklar oranı", "pct", "monthly", "ratio",
           ["NPL oranı", "takip oranı", "batık kredi oranı", "NPL ratio"], "aktif kalitesi"),
    Series("syn:bddk:toplam_mevduat", "Toplam mevduat", "TRY_mn", "monthly", "stock",
           ["mevduat", "deposits", "toplam mevduat hacmi"], "mevduat"),
    Series("syn:bddk:tl_mevduat", "TL mevduat", "TRY_mn", "monthly", "stock",
           ["Türk lirası mevduat", "TL deposits", "lira mevduatı"], "mevduat"),
    Series("syn:bddk:yp_mevduat", "Yabancı para mevduat (TL karşılığı)", "TRY_mn", "monthly", "stock",
           ["döviz mevduatı", "YP mevduat", "FX deposits", "dolarizasyon mevduat"], "mevduat"),
    Series("syn:evds:mevduat_faizi", "TL mevduat faiz oranı (3 aya kadar vadeli, ağırlıklı ort.)", "pct", "weekly", "rate",
           ["mevduat faizi", "deposit rate", "vadeli mevduat faizi"], "faiz/mevduat"),
    Series("syn:evds:ticari_kredi_faizi", "Ticari kredi faiz oranı (TL, ağırlıklı ort.)", "pct", "weekly", "rate",
           ["ticari faiz", "commercial loan rate", "işletme kredisi faizi"], "faiz/kredi"),
    Series("syn:evds:ihtiyac_kredi_faizi", "İhtiyaç kredisi faiz oranı (TL)", "pct", "weekly", "rate",
           ["ihtiyaç faizi", "consumer loan rate", "tüketici kredisi faizi"], "faiz/kredi"),
    Series("syn:evds:tasit_kredi_faizi", "Taşıt kredisi faiz oranı (TL)", "pct", "weekly", "rate",
           ["araç kredisi faizi", "oto kredi faizi", "vehicle loan rate"], "faiz/kredi"),
    Series("syn:evds:usd_try", "ABD doları / TL kuru (alış)", "TRY", "daily", "rate",
           ["dolar kuru", "USD/TRY", "dolar", "kur"], "döviz"),
    Series("syn:evds:eur_try", "Euro / TL kuru (alış)", "TRY", "daily", "rate",
           ["euro kuru", "EUR/TRY", "avro"], "döviz"),
    Series("syn:evds:altin_ons", "Altın ons fiyatı (USD)", "USD", "daily", "rate",
           ["ons altın", "gold price", "altın fiyatı"], "emtia"),
    Series("syn:evds:rezerv", "TCMB brüt döviz rezervleri", "USD_mn", "weekly", "stock",
           ["brüt rezerv", "döviz rezervi", "FX reserves", "merkez bankası rezervleri"], "dış varlıklar"),
    Series("syn:evds:m2", "Para arzı M2", "TRY_mn", "weekly", "stock",
           ["M2", "para arzı", "money supply"], "parasal büyüklükler"),
    Series("syn:evds:cari_denge", "Cari işlemler dengesi", "USD_mn", "monthly", "flow_periodic",
           ["cari açık", "cari denge", "current account"], "ödemeler dengesi"),
    Series("syn:evds:ihracat", "İhracat (FOB)", "USD_mn", "monthly", "flow_periodic",
           ["ihracat", "exports", "dış satım"], "dış ticaret"),
    Series("syn:evds:ithalat", "İthalat (CIF)", "USD_mn", "monthly", "flow_periodic",
           ["ithalat", "imports", "dış alım"], "dış ticaret"),
    Series("syn:evds:issizlik", "İşsizlik oranı (mevsim etkilerinden arındırılmış)", "pct", "monthly", "ratio",
           ["işsizlik", "unemployment rate", "işsizlik oranı"], "işgücü"),
    Series("syn:evds:sanayi_uretim", "Sanayi üretim endeksi (takvim etkisinden arındırılmış)", "index", "monthly", "index",
           ["sanayi üretimi", "industrial production", "SÜE"], "reel sektör"),
    Series("syn:evds:kapasite", "İmalat sanayi kapasite kullanım oranı", "pct", "monthly", "ratio",
           ["KKO", "kapasite kullanımı", "capacity utilization"], "reel sektör"),
    Series("syn:evds:guven_endeksi", "Tüketici güven endeksi", "index", "monthly", "index",
           ["tüketici güveni", "consumer confidence"], "anketler"),
    Series("syn:evds:konut_satis", "Konut satışları (toplam adet)", "count", "monthly", "flow_periodic",
           ["ev satışları", "konut satış adedi", "house sales"], "reel sektör/konut"),
    Series("syn:evds:ipotekli_konut_satis", "İpotekli konut satışları (adet)", "count", "monthly", "flow_periodic",
           ["kredili konut satışı", "mortgage sales", "ipotekli satış"], "reel sektör/konut"),
    Series("syn:bddk:aktif_toplam", "Bankacılık sektörü toplam aktifler", "TRY_mn", "monthly", "stock",
           ["toplam aktif", "aktif büyüklüğü", "total assets", "bilanço büyüklüğü"], "bilanço"),
    Series("syn:bddk:ozkaynak", "Bankacılık sektörü özkaynaklar", "TRY_mn", "monthly", "stock",
           ["özkaynak", "sermaye", "equity"], "bilanço"),
    Series("syn:bddk:net_kar", "Dönem net kârı (yılbaşından itibaren kümülatif)", "TRY_mn", "monthly", "flow_ytd",
           ["net kâr", "banka kârı", "net income", "kâr"], "kâr/zarar"),
    Series("syn:bddk:syr", "Sermaye yeterliliği standart oranı", "pct", "monthly", "ratio",
           ["SYR", "sermaye yeterliliği", "CAR", "capital adequacy ratio"], "rasyolar"),
    Series("syn:bddk:kredi_mevduat_orani", "Kredi / mevduat oranı", "pct", "monthly", "ratio",
           ["kredi mevduat oranı", "loan to deposit", "K/M oranı"], "rasyolar"),
    Series("syn:bddk:sube_sayisi", "Şube sayısı", "count", "monthly", "count",
           ["şube adedi", "branch count", "banka şubesi"], "yapısal"),
    Series("syn:bddk:personel_sayisi", "Personel sayısı", "count", "monthly", "count",
           ["çalışan sayısı", "banka personeli", "employees"], "yapısal"),
    Series("syn:bddk:katilim_konut", "Konut finansmanı bakiyesi (katılım bankaları)", "TRY_mn", "monthly", "stock",
           ["katılım konut", "katılım bankası konut finansmanı", "participation housing finance"], "krediler/katılım"),
    Series("syn:bddk:kamu_konut", "Konut kredileri bakiyesi (kamu bankaları)", "TRY_mn", "monthly", "stock",
           ["kamu bankası konut kredisi", "devlet bankası mortgage"], "krediler/tüketici"),
    Series("syn:bddk:yabanci_konut", "Konut kredileri bakiyesi (yabancı bankalar)", "TRY_mn", "monthly", "stock",
           ["yabancı banka konut kredisi"], "krediler/tüketici"),
    Series("syn:bddk:konut_kredi_haftalik", "Konut kredileri bakiyesi (haftalık bülten)", "TRY_mn", "weekly", "stock",
           ["haftalık konut kredisi", "weekly housing loans"], "krediler/tüketici"),
    Series("syn:bddk:sektorel_insaat", "Sektörel kredi dağılımı – inşaat", "TRY_th", "monthly", "stock",
           ["inşaat kredileri", "construction loans", "inşaat sektörü kredisi"], "krediler/sektörel"),
    Series("syn:bddk:sektorel_tarim", "Sektörel kredi dağılımı – tarım", "TRY_th", "monthly", "stock",
           ["tarım kredileri", "agriculture loans", "çiftçi kredisi"], "krediler/sektörel"),
    Series("syn:bddk:sektorel_enerji", "Sektörel kredi dağılımı – enerji", "TRY_th", "monthly", "stock",
           ["enerji kredileri", "energy loans"], "krediler/sektörel"),
    Series("syn:bist:xtumy", "BIST TÜM-100 endeksi (XTUMY) kapanış", "index", "daily", "index",
           ["XTUMY", "BIST tüm 100", "borsa endeksi", "BIST all shares 100"], "piyasa"),
    Series("syn:bist:xu100", "BIST 100 endeksi (XU100) kapanış", "index", "daily", "index",
           ["BIST100", "borsa", "XU100", "hisse endeksi"], "piyasa"),
    Series("syn:evds:tahvil_faizi", "2 yıllık devlet tahvili faizi (gösterge)", "pct", "daily", "rate",
           ["gösterge tahvil", "bono faizi", "bond yield", "tahvil faizi"], "faiz/piyasa"),
    Series("syn:evds:kkdf", "Kaynak kullanımını destekleme fonu oranı (tüketici kredileri)", "pct", "monthly", "rate",
           ["KKDF", "fon kesintisi"], "vergi/fon"),
    Series("syn:evds:bsmv", "Banka ve sigorta muameleleri vergisi oranı", "pct", "monthly", "rate",
           ["BSMV", "muamele vergisi"], "vergi/fon"),
    Series("syn:evds:kira_endeksi", "Kira fiyat endeksi", "index", "monthly", "index",
           ["kira endeksi", "kiralar", "rent index"], "reel sektör/konut"),
    Series("syn:evds:yeni_konut_fiyat", "Yeni konutlar fiyat endeksi (YKFE)", "index", "monthly", "index",
           ["YKFE", "yeni konut fiyatları", "sıfır konut fiyat endeksi"], "reel sektör/konut"),
    Series("syn:evds:reel_efektif_kur", "Reel efektif döviz kuru (TÜFE bazlı)", "index", "monthly", "index",
           ["REK", "reel kur", "real effective exchange rate"], "döviz"),
    Series("syn:evds:enflasyon_beklentisi", "12 ay sonrası TÜFE beklentisi (piyasa katılımcıları)", "pct", "monthly", "rate",
           ["enflasyon beklentisi", "beklenen enflasyon", "inflation expectations"], "anketler"),
    Series("syn:bddk:finturk_istanbul_konut", "FinTürk – İstanbul konut kredileri", "TRY_th", "quarterly", "stock",
           ["İstanbul konut kredisi", "il bazında konut kredisi İstanbul"], "krediler/il"),
    Series("syn:bddk:finturk_ankara_konut", "FinTürk – Ankara konut kredileri", "TRY_th", "quarterly", "stock",
           ["Ankara konut kredisi"], "krediler/il"),
]

# Hand-written test queries: (query, target_id, category)
QUERIES: list[tuple[str, str, str]] = [
    ("konut kredisi bakiyesi", "syn:bddk:konut_kredi_bakiye", "exact"),
    ("konut kredisi faiz oranı", "syn:evds:konut_kredi_faiz", "exact"),
    ("tüketici fiyat endeksi", "syn:evds:tufe", "exact"),
    ("politika faizi", "syn:evds:politika_faizi", "exact"),
    ("takipteki alacaklar oranı", "syn:bddk:npl_orani", "exact"),
    ("KFE", "syn:evds:kfe", "abbrev"),
    ("TÜFE", "syn:evds:tufe", "abbrev"),
    ("NPL", "syn:bddk:takipteki_alacak", "abbrev"),
    ("SYR", "syn:bddk:syr", "abbrev"),
    ("XTUMY", "syn:bist:xtumy", "abbrev"),
    ("KKDF", "syn:evds:kkdf", "abbrev"),
    ("mortgage bakiyesi", "syn:bddk:konut_kredi_bakiye", "synonym"),
    ("ev kredisi faizi", "syn:evds:konut_kredi_faiz", "synonym"),
    ("ev fiyatları", "syn:evds:kfe", "synonym"),
    ("enflasyon", "syn:evds:tufe", "synonym"),
    ("batık krediler", "syn:bddk:takipteki_alacak", "synonym"),
    ("araba kredisi", "syn:bddk:tasit_kredi_bakiye", "synonym"),
    ("döviz mevduatı", "syn:bddk:yp_mevduat", "synonym"),
    ("dolar kuru", "syn:evds:usd_try", "synonym"),
    ("banka kârı", "syn:bddk:net_kar", "synonym"),
    ("housing loans", "syn:bddk:konut_kredi_bakiye", "english"),
    ("housing loan interest rate", "syn:evds:konut_kredi_faiz", "english"),
    ("house price index", "syn:evds:kfe", "english"),
    ("CPI", "syn:evds:tufe", "english"),
    ("unemployment rate", "syn:evds:issizlik", "english"),
    ("capital adequacy ratio", "syn:bddk:syr", "english"),
    ("konut kredsi bakiyesi", "syn:bddk:konut_kredi_bakiye", "typo"),
    ("tuketici fiyat endeksi", "syn:evds:tufe", "typo"),
    ("politka faizi", "syn:evds:politika_faizi", "typo"),
    ("issizlik orani", "syn:evds:issizlik", "typo"),
    ("konut fiyat endeksi", "syn:evds:kfe", "misleading"),          # vs konut kredisi
    ("konut kredisi faizi", "syn:evds:konut_kredi_faiz", "misleading"),  # vs konut kredisi bakiyesi
    ("katılım bankaları konut finansmanı", "syn:bddk:katilim_konut", "misleading"),
    ("kamu bankaları konut kredisi", "syn:bddk:kamu_konut", "misleading"),
    ("haftalık konut kredisi", "syn:bddk:konut_kredi_haftalik", "misleading"),
    ("yeni konut fiyatları", "syn:evds:yeni_konut_fiyat", "misleading"),
    ("İstanbul'daki konut kredileri", "syn:bddk:finturk_istanbul_konut", "misleading"),
    ("ipotekli konut satışları", "syn:evds:ipotekli_konut_satis", "misleading"),
    ("mevduat faizi", "syn:evds:mevduat_faizi", "misleading"),         # vs toplam mevduat
    ("toplam mevduat hacmi", "syn:bddk:toplam_mevduat", "misleading"),
    ("bankaların özkaynağı ne kadar", "syn:bddk:ozkaynak", "natural"),
    ("kaç banka şubesi var", "syn:bddk:sube_sayisi", "natural"),
    ("TCMB'nin döviz rezervi", "syn:evds:rezerv", "natural"),
    ("cari açık ne durumda", "syn:evds:cari_denge", "natural"),
    ("inşaat sektörüne verilen krediler", "syn:bddk:sektorel_insaat", "natural"),
    ("borsa endeksi kapanış", "syn:bist:xu100", "natural"),
    ("işletmelere verilen krediler", "syn:bddk:ticari_kredi_bakiye", "natural"),
    ("kredi kartı borçları", "syn:bddk:kredi_karti_bakiye", "natural"),
    ("kiralar ne kadar arttı", "syn:evds:kira_endeksi", "natural"),
    ("piyasanın enflasyon beklentisi", "syn:evds:enflasyon_beklentisi", "natural"),
]

_ENTITIES = ["sektör", "mevduat bankaları", "katılım bankaları", "kamu bankaları", "yerli özel bankalar", "yabancı bankalar",
             "kalkınma bankaları", "İstanbul", "Ankara", "İzmir", "Bursa", "Antalya", "Adana", "Konya", "Gaziantep", "Kocaeli"]
_MEASURES = [("nakdi krediler", "TRY_mn", "stock"), ("gayrinakdi krediler", "TRY_mn", "stock"), ("menkul değerler", "TRY_mn", "stock"),
             ("faiz gelirleri", "TRY_mn", "flow_ytd"), ("faiz giderleri", "TRY_mn", "flow_ytd"), ("komisyon gelirleri", "TRY_mn", "flow_ytd"),
             ("likit aktifler", "TRY_mn", "stock"), ("repo işlemleri", "TRY_mn", "stock"), ("türev işlemler", "TRY_mn", "stock"),
             ("ATM sayısı", "count", "count"), ("POS sayısı", "count", "count"), ("müşteri sayısı", "count", "count"),
             ("yabancı para krediler", "TRY_mn", "stock"), ("tarım kredileri", "TRY_th", "stock"), ("turizm kredileri", "TRY_th", "stock"),
             ("tekstil kredileri", "TRY_th", "stock"), ("ulaştırma kredileri", "TRY_th", "stock"), ("sağlık sektörü kredileri", "TRY_th", "stock"),
             ("eğitim kredileri", "TRY_th", "stock"), ("madencilik kredileri", "TRY_th", "stock")]
_FREQS = ["monthly", "weekly", "quarterly"]


def build(n: int, seed: int = 7) -> list[Series]:
    """Return REAL + filler up to n series (REAL always included, shuffled)."""
    rng = random.Random(seed)
    out = list(REAL)
    i = 0
    while len(out) < n:
        ent = _ENTITIES[i % len(_ENTITIES)]
        meas, unit, mt = _MEASURES[(i // len(_ENTITIES)) % len(_MEASURES)]
        freq = _FREQS[(i // (len(_ENTITIES) * len(_MEASURES))) % len(_FREQS)]
        k = i // (len(_ENTITIES) * len(_MEASURES) * len(_FREQS))
        suffix = f" (v{k})" if k else ""
        sid = f"syn:fill:{i:05d}"
        out.append(Series(sid, f"{meas.capitalize()} – {ent}{suffix}", unit, freq, mt, [f"{ent} {meas}"], "filler"))
        i += 1
    rng.shuffle(out)
    return out[:n] if n >= len(REAL) else out
