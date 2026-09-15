"""Yanlış-dosya tespiti ablation'ı (brief §129): hangi sinyal hard-negative'i ayırıyor?

Kullanım (repo kökünden):
    python scripts/ueb_wrongfile_ablation.py [--no-llm] [--threads 3] [--out docs/experiments/ueb_wrongfile_ablation.json]

Havuz: incoming/ueb/* (UEB fikstürleri) + scripts/.ueb_scratch/pool/* (ek hard-negative / ilgisiz dosyalar).
12 soru; her (soru, dosya) çifti için altın etiket: R (uygun), H (anlamca yakın ama yanlış), I (ilgisiz).

Kollar (her biri (soru, dosya) → skor ∈ [0,1] ve/veya karar):
  A  filename        dosya adı ile soru kök-örtüşmesi (Jaccard)
  B  schema          kolon başlıkları ile örtüşme
  C  embed_meta      kosinüs(soru, dosya adı + başlıklar)                       [MIA embedding]
  D  bm25            BM25(soru → dosya adı + başlıklar + 3 örnek satır)
  E  embed_period    C × dönem kapsama (soru yılı dosyada var mı)
  F  embed_full      kosinüs(soru, ad + başlık + 3 örnek satır + yıl aralığı)   [MIA embedding]
  G  llm_judge       Qwen: "bu dosya bu soru için gerekli ölçümleri içeriyor mu?" (evet/kısmen/hayır)
  H  contract_det    deterministik gereksinim kontrolü: kavram sözlüğü + dönem + granülarite + makullük
  R  repo_gate       depodaki builder/relevance.assess (13 Eylül ilgi kapısı), katalogsuz
  I  H_then_G        H kesin karar verirse o; "kısmen" ise G'ye sorulur (LLM çağrısı sayılır)

Ölçütler: top-1 seçim (R@1), I'yi ret oranı, H'yi ret oranı, R'yi kabul oranı, dengeli doğruluk,
gecikme, LLM çağrısı. Skor kolları için eşik, dengeli doğruluğu en yükselten τ (iyimser, raporda söylenir).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CORE = ROOT / "agent-core"
sys.path.insert(0, str(CORE / "src"))
from kkb_agent.config import load_settings  # noqa: E402
from kkb_agent.builder.profile import profile_table, propose  # noqa: E402
from kkb_agent.builder.relevance import assess, content_terms, stem, years_in  # noqa: E402
from kkb_agent.builder.read import _table_from_bytes  # noqa: E402
from kkb_agent.core.lexical import Bm25Index  # noqa: E402
from kkb_agent.contracts.retrieval import Candidate  # noqa: E402

POOL_EXTRA = HERE / ".ueb_scratch" / "pool"
FIXTURES = ROOT / "incoming" / "ueb"


# ----------------------------------------------------------------------------- havuz
def make_extra_pool() -> None:
    POOL_EXTRA.mkdir(parents=True, exist_ok=True)
    m24 = [d.isoformat() for d in pd.date_range("2024-01-31", "2024-12-31", freq="ME").date]
    w24 = [d.isoformat() for d in pd.date_range("2024-01-05", "2024-12-27", freq="W-FRI").date]
    files = {
        "konut_basvuru_adedi.csv": pd.DataFrame({"donem": m24, "basvuru_adedi": [41000 + i * 900 for i in range(12)]}),
        "konut_satis_adedi.csv": pd.DataFrame({"donem": m24, "satis_adedi": [80000 + (i % 4) * 7000 for i in range(12)]}),
        "tuketici_kredisi_toplam.csv": pd.DataFrame({"donem": m24, "tuketici_kredisi_bakiye": [2100000 + i * 60000 for i in range(12)]}),
        "faiz_giderleri.csv": pd.DataFrame({"donem": m24, "faiz_gideri": [150000 + i * 4000 for i in range(12)]}),
        "mevduat_faizi.csv": pd.DataFrame({"donem": m24, "mevduat_faiz_orani": [round(42 + i * 0.6, 2) for i in range(12)]}),
        "konut_kredisi_faizi_haftalik.csv": pd.DataFrame({"tarih": w24, "konut_kredisi_faiz_orani": [round(38 + (i % 9) * 0.4, 2) for i in range(len(w24))]}),
        "ihtiyac_kredisi_2024.csv": pd.DataFrame({"donem": m24, "ihtiyac_kredisi_bakiye": [1200000 + i * 20000 for i in range(12)]}),
        "otobus_tarifesi.csv": pd.DataFrame({"hat": ["34", "500T", "E-10"], "kalkis": ["06:00", "06:30", "07:00"], "sefer_sayisi": [40, 25, 18]}),
        "hasta_yatis_2024.csv": pd.DataFrame({"donem": m24, "yatis_sayisi": [12000 + i * 150 for i in range(12)]}),
        "perakende_satis_2024.csv": pd.DataFrame({"donem": m24, "satis_tutari": [9_500_000 + i * 120_000 for i in range(12)]}),
    }
    for name, df in files.items():
        df.to_csv(POOL_EXTRA / name, index=False)


@dataclass
class FileCard:
    name: str
    path: Path
    frame: pd.DataFrame
    headers: list[str]
    sample: str
    years: tuple[int, int] | None
    freq: str | None
    numeric_median: dict[str, float] = field(default_factory=dict)
    mapping: object = None

    @property
    def stem_name(self) -> str:
        return self.path.stem

    def text_meta(self) -> str:
        return f"{self.stem_name.replace('_', ' ')} | kolonlar: {', '.join(self.headers)}"

    def text_full(self) -> str:
        yrs = f"{self.years[0]}–{self.years[1]}" if self.years else "bilinmiyor"
        return (f"{self.text_meta()} | frekans: {self.freq or 'bilinmiyor'} | yıl aralığı: {yrs} | "
                f"satır: {len(self.frame)} | örnek:\n{self.sample}")


def load_pool() -> list[FileCard]:
    cards: list[FileCard] = []
    for d in (FIXTURES, POOL_EXTRA):
        for p in sorted(d.iterdir()):
            if p.suffix.lower() not in (".csv", ".xlsx"):
                continue
            content = p.read_bytes()
            sheet = None
            if p.suffix.lower() == ".xlsx":
                # ADR-0054 (15 Eyl): çok sayfalı xlsx `sheet` ister; havuzda veri sayfası "Veri", yoksa son sayfa.
                from kkb_agent.builder.read import excel_sheets
                names = excel_sheets(content)
                if len(names) > 1:
                    sheet = "Veri" if "Veri" in names else names[-1]
            frame = _table_from_bytes(content, p.name, sheet=sheet)
            prof = profile_table(frame)
            mapping, sem = propose(prof, frame, series_id="adhoc:x")
            years = None
            if mapping is not None:
                from kkb_agent.builder.relevance import file_year_range
                years = file_year_range(frame, mapping)
            if years is None:
                ys = sorted({int(y) for col in frame.columns for y in re.findall(r"\b(20[0-2][0-9])\b", " ".join(frame[col].astype(str)))})
                years = (ys[0], ys[-1]) if ys else None
            med: dict[str, float] = {}
            for col in frame.columns:
                vals = pd.to_numeric(frame[col].str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce").dropna()
                if len(vals) >= 3:
                    med[str(col)] = float(vals.median())
            freq = sem.frequency if sem is not None else ("yearly" if any(str(c).lower().startswith("yil") for c in frame.columns) and mapping is None else None)
            cards.append(FileCard(name=p.name, path=p, frame=frame, headers=[str(c) for c in frame.columns],
                                  sample=frame.head(3).to_string(index=False)[:300], years=years, freq=freq,
                                  numeric_median=med, mapping=mapping))
    return cards


# ----------------------------------------------------------------------------- sorular ve altın
@dataclass
class Q:
    id: str
    text: str
    relevant: set[str]
    hard: set[str]


KONUT24 = {"hsg_ln_2024.csv", "konut_kredisi_2024_revize.csv", "konut_kredisi_2024_notlu.csv", "konut_kredisi_2024_toplamli.csv",
           "konut_kredisi_2024_mukerrer.csv", "konut_kredisi_2024_eksik.csv", "konut_kredisi_bin_tl.csv", "konut_kredisi_2024.xlsx",
           "konut_kredisi_ornek.csv"}
KONUT_HARD_FOR_BAKIYE = {"konut_fiyat_endeksi.csv", "konut_basvuru_adedi.csv", "konut_satis_adedi.csv", "tuketici_kredisi_toplam.csv",
                         "istanbul_konut_kredisi_2024.csv", "konut_kredisi_2019_2021.csv", "konut_kredisi_yillik.csv",
                         "takipteki_konut_orani_2024.csv", "konut_kredisi_2025_8ay.csv", "ihtiyac_kredisi_2024.csv",
                         "konut_faiz_orani_2024.csv", "konut_kredisi_faizi_haftalik.csv"}
QUESTIONS = [
    Q("Q01", "2024'te konut kredisi bakiyesi aylık nasıl değişti?", KONUT24, KONUT_HARD_FOR_BAKIYE),
    Q("Q02", "Konut kredisi faiz oranı 2024'te nasıl seyretti?", {"konut_kredisi_faizi_haftalik.csv"},
      {"konut_faiz_orani_2024.csv", "mevduat_faizi.csv", "faiz_giderleri.csv", "konut_fiyat_endeksi.csv"} | KONUT24),
    Q("Q03", "Konut fiyat endeksi 2024'te ne kadar arttı?", {"konut_fiyat_endeksi.csv"},
      KONUT24 | {"konut_satis_adedi.csv", "konut_basvuru_adedi.csv", "tufe_yillik_locale.csv", "istanbul_konut_kredisi_2024.csv"}),
    Q("Q04", "2024 kredi kartı işlem hacmi aylık ne kadar?", {"kredi_karti_islemleri.csv"}, KONUT24 | {"tuketici_kredisi_toplam.csv", "ihtiyac_kredisi_2024.csv"}),
    Q("Q05", "2024'te takipteki konut kredisi oranı nasıl değişti?", {"takipteki_konut_orani_2024.csv"}, KONUT24 | {"konut_faiz_orani_2024.csv", "mevduat_faizi.csv"}),
    Q("Q06", "2025 yıllık TÜFE enflasyonu ne kadar?", {"tufe_yillik_locale.csv"}, {"konut_fiyat_endeksi.csv", "mevduat_faizi.csv", "konut_kredisi_2025_8ay.csv"}),
    Q("Q07", "2024'te aylık konut satış adedi nasıl değişti?", {"konut_satis_adedi.csv"}, KONUT24 | {"konut_basvuru_adedi.csv", "konut_fiyat_endeksi.csv", "perakende_satis_2024.csv"}),
    Q("Q08", "İhtiyaç kredisi bakiyesi 2024 Aralık'ta ne kadardı?", {"ihtiyac_kredisi_2024.csv"}, KONUT24 | {"tuketici_kredisi_toplam.csv"}),
    Q("Q09", "2019–2020 döneminde konut kredisi bakiyesi nasıl değişti?", {"konut_kredisi_2019_2021.csv"}, KONUT24 | {"konut_kredisi_yillik.csv", "konut_kredisi_2025_8ay.csv"}),
    Q("Q10", "Mortgage balance in December 2024?", KONUT24, KONUT_HARD_FOR_BAKIYE),
    Q("Q11", "2024'te konut kredisi başvuru sayısı nasıl değişti?", {"konut_basvuru_adedi.csv"}, KONUT24 | {"konut_satis_adedi.csv"}),
    Q("Q12", "Faiz oranları düştüğünde konut kredileri 2024'te nasıl değişti?", KONUT24 | {"konut_kredisi_faizi_haftalik.csv"},
      {"konut_fiyat_endeksi.csv", "konut_faiz_orani_2024.csv", "mevduat_faizi.csv", "faiz_giderleri.csv", "kredi_karti_islemleri.csv"}),
]


def gold(q: Q, name: str) -> str:
    return "R" if name in q.relevant else ("H" if name in q.hard else "I")


# ----------------------------------------------------------------------------- kavram sözlüğü (H kolu)
# kavram → kök listesi (relevance.stem ile 5 harf). Katalog alias'ları buraya girer; kısaltmalar (hsg/ln/bal) dahil.
LEX: dict[str, set[str]] = {
    "konut": {"konut", "hsg", "mortg", "housi", "house", "ev"},
    "kredi": {"kredi", "krd", "ln", "loan", "mortg", "credi"},
    "bakiye": {"bakiy", "hacim", "tutar", "bal", "balan", "stok", "volum", "amoun", "hacmi"},
    "faiz": {"faiz", "rate", "int"},
    "fiyat_endeksi": {"kfe", "hpi", "endek", "fiyat", "price"},
    "tufe": {"tüfe", "tufe", "enfla", "cpi", "infla"},
    "kredi_karti": {"kart", "card"},
    "takip": {"takip", "npl", "sorun", "nonpe"},
    "satis": {"satış", "satis", "sale"},
    "basvuru": {"başvu", "basvu", "appli"},
    "ihtiyac": {"ihtiy", "ihtiya"},
    "mevduat": {"mevdu", "depos"},
    "gider": {"gider", "expen"},
}
# soruda geçtiğinde GEREKLİ kavramlar: (tetikleyici kök kümesi) → gereken kavramlar
RULES: list[tuple[set[str], set[str]]] = [
    ({"konut", "mortg", "housi", "ev"}, {"konut"}),
    ({"kredi", "mortg", "loan", "kredi̇"}, {"kredi"}),
    ({"bakiy", "hacim", "hacmi", "balan", "tutar"}, {"bakiye"}),
    ({"faiz", "rate"}, {"faiz"}),
    ({"fiyat", "endek", "kfe", "price"}, {"fiyat_endeksi"}),
    ({"tüfe", "tufe", "enfla", "cpi"}, {"tufe"}),
    ({"kart", "card"}, {"kredi_karti"}),
    ({"takip", "npl"}, {"takip"}),
    ({"satış", "satis", "sale"}, {"satis"}),
    ({"başvu", "basvu", "appli"}, {"basvuru"}),
    ({"ihtiy"}, {"ihtiyac"}),
]
_TOK = re.compile(r"[a-zçğıöşüâîû0-9]+", re.I)
#: Ölçüm kavramları: analizin ÜZERİNDE çalıştığı şey. Eksikse dosya soruyu cevaplayamaz (ret).
MEASURES = {"bakiye", "faiz", "fiyat_endeksi", "tufe", "takip", "satis", "basvuru"}
#: İlişki sorusu: iki özne (ölçüm/varlık) — tek özneyi taşıyan dosya "kısmen"dir, ret değil.
_RELATION = re.compile(r"ilişki|etki|düştüğünde|arttığında|yükseldiğinde|karşılaştır|arasında|birlikte|öncül|korelasyon|"
                       r"relationship|when |versus|\bvs\b", re.I)
_MONTHLY = re.compile(r"\bayl[ıi]k\b|ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık|"
                      r"january|february|march|april|june|july|august|september|october|november|december|monthly", re.I)


def toks(text: str) -> set[str]:
    return {t.replace("İ", "i").replace("I", "ı").casefold() for t in _TOK.findall(text or "") if len(t) >= 2}


def _match(tokens: set[str], roots: set[str]) -> bool:
    """Önek eşleşmesi: 'kartı' ~ 'kart', 'kredileri' ~ 'kredi'; kök 2 harfse tam eşleşme ister (ln, ev)."""
    return any((t == r) if len(r) <= 2 else t.startswith(r) for t in tokens for r in roots)


def required_concepts(question: str) -> set[str]:
    qt = toks(question)
    req: set[str] = set()
    for trig, needs in RULES:
        if _match(qt, trig):
            req |= needs
    # "fiyat endeksi" sorusunda 'konut' zorunlu değil değil; ama 'kredi' istenmedikçe 'kredi' gerekmez.
    # Kredi kartı sorusu 'kredi' kavramını gerektirmez: kart tek başına yeter.
    if "kredi_karti" in req:
        req.discard("kredi")
    if "fiyat_endeksi" in req or "tufe" in req or "satis" in req or "basvuru" in req or "takip" in req:
        req.discard("bakiye")
    if "takip" in req or "basvuru" in req or "satis" in req:
        req.discard("kredi")   # 'konut kredisi başvurusu' / 'takipteki konut' — kredi burada niteleyici, ayrı kavram değil
    return req


def file_concepts(card: FileCard) -> set[str]:
    ft = toks(card.stem_name.replace("_", " ") + " " + " ".join(card.headers))
    out = set()
    for c, roots in LEX.items():
        if _match(ft, roots):
            out.add(c)
    return out


def scoped_dimension(card: FileCard) -> str | None:
    """Tek değerli metin kolonu = dosya bir alt kümeye kısıtlı (il=İstanbul gibi). Genel sinyal, alan bilgisi yok."""
    for col in card.frame.columns:
        s = card.frame[col].astype(str).str.strip()
        if s.empty or pd.to_numeric(s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce").notna().mean() > 0.5:
            continue
        vals = set(s[s != ""])
        if len(vals) == 1 and len(card.frame) >= 3 and not re.search(r"\d{4}", next(iter(vals))):
            return f"{col}={next(iter(vals))}"
    return None


def contract_check(q: Q, card: FileCard) -> tuple[str, float, str]:
    """→ (karar: accept|partial|reject, skor, gerekçe)."""
    req = required_concepts(q.text)
    have = file_concepts(card)
    # makullük: faiz/oran başlığı ama değer medyanı > 1000 → 'faiz' güvenilir değil
    if "faiz" in have:
        for col, m in card.numeric_median.items():
            if re.search(r"faiz|oran|rate", col, re.I) and abs(m) > 1000:
                have.discard("faiz")
                have.add("bakiye")
                break
    reasons = []
    qy = years_in(q.text)
    period_ok = True
    if qy and card.years:
        period_ok = any(card.years[0] <= y <= card.years[1] for y in qy)
        if not period_ok:
            reasons.append(f"dönem: soru {sorted(qy)}, dosya {card.years[0]}–{card.years[1]}")
    gran_ok = True
    if _MONTHLY.search(q.text) and (card.freq == "yearly" or (card.mapping is None and any(h.lower().startswith("yil") for h in card.headers))):
        gran_ok = False
        reasons.append("granülarite: ay düzeyi istendi, dosya yıllık")
    # Karar sırası: (1) gereksinim çıkarılamadı → kısmen; (2) dönem/granülarite → ret; (3) aranan ÖLÇÜM hiç yoksa → ret;
    # (4) niteleyici (konut/ihtiyaç/…) eksikse → ret (farklı varlık/segment); (5) ölçümlerin bir kısmı varsa → kısmen
    # (çok dosyalı analiz); (6) tek değerli boyut kolonu → kısmen (alt küme); (7) hepsi var → kabul.
    if not req:
        return "partial", 0.5, "sorudan gereksinim çıkarılamadı"
    if not period_ok or not gran_ok:
        return "reject", 0.0, "; ".join(reasons)
    m_req, m_have = req & MEASURES, have & MEASURES
    q_req = req - MEASURES
    if m_req and not (m_req & m_have):
        if _RELATION.search(q.text) and q_req and q_req <= have and m_have:
            return "partial", 0.55, f"ilişki sorusu: dosya {sorted(q_req)} öznesini taşıyor ama {sorted(m_req)} ölçümü yok — ikinci kaynak gerekir"
        return "reject", 0.0, f"aranan ölçüm yok: {sorted(m_req)}; dosyada: {sorted(m_have) or '—'}"
    if q_req - have:
        return "reject", 0.2, f"varlık/segment farklı: eksik {sorted(q_req - have)}; dosyada {sorted(have)}"
    if m_req - m_have:
        return "partial", 0.6, f"ölçümlerin bir kısmı var ({sorted(m_have)}), eksik {sorted(m_req - m_have)} — ikinci dosya/seri gerekir"
    scope = scoped_dimension(card)
    if scope and not _match(toks(q.text), {scope.split('=', 1)[1].casefold()[:5]}):
        return "partial", 0.7, f"dosya bir alt kümeye kısıtlı ({scope}); soru bunu söylemiyor"
    return "accept", 1.0, "gerekli kavramlar var: " + ", ".join(sorted(req))


# ----------------------------------------------------------------------------- kollar
def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if (a | b) else 0.0


def arm_filename(q: Q, c: FileCard) -> float:
    return jaccard(content_terms(q.text), content_terms(c.stem_name.replace("_", " ")))


def arm_schema(q: Q, c: FileCard) -> float:
    return jaccard(content_terms(q.text), content_terms(" ".join(c.headers)))


def cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b / ((np.linalg.norm(a) or 1) * (np.linalg.norm(b) or 1)))


def llm_judge(client, q: Q, c: FileCard) -> tuple[str, str]:
    from kkb_agent.llm.base import ChatMessage
    prompt = (
        "Bir veri dosyasının, kullanıcının sorusunu cevaplamak için GEREKLİ ölçümleri içerip içermediğine karar ver. "
        "Anlam düzeyinde düşün: 'konut fiyat endeksi' ≠ 'konut kredisi bakiyesi'; 'faiz oranı' başlıklı ama 500.000 gibi "
        "değerler taşıyan kolon faiz oranı olamaz. Yalnız JSON döndür: "
        '{"uygun": "evet|kısmen|hayır", "eksik": ["..."], "gerekce": "tek cümle"}\n\n'
        f"SORU: {q.text}\n\nDOSYA KARTI:\n{c.text_full()}\n"
    )
    resp = client.chat([ChatMessage(role="user", content=prompt)], temperature=0.0, max_tokens=200)
    text = resp.content or ""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        obj = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        obj = {}
    verdict = str(obj.get("uygun", "")).lower().strip()
    if verdict not in ("evet", "kısmen", "hayır"):
        verdict = "hayır" if "hayır" in text.lower() else ("evet" if "evet" in text.lower() else "kısmen")
    return verdict, str(obj.get("gerekce", text[:120]))


def arm_repo_gate(q: Q, c: FileCard) -> tuple[bool, float]:
    rep = assess(q.text, q.text, str(c.path), c.frame, c.mapping, catalog=())
    return rep.irrelevant, (rep.score / rep.applicable if rep.applicable else 0.5)


# ----------------------------------------------------------------------------- değerlendirme
def evaluate(scores: dict[tuple[str, str], float], decisions: dict[tuple[str, str], bool] | None, labels: dict[tuple[str, str], str],
             questions: list[Q], names: list[str]) -> dict:
    """decisions: (q,f) → reject? Yoksa skor eşiğiyle üretilir (dengeli doğruluk en iyi τ)."""
    pairs = list(labels)
    if decisions is None:
        best = None
        for tau in sorted({round(scores[p], 4) for p in pairs} | {0.0, 1.0}):
            d = {p: scores[p] < tau for p in pairs}
            ba = balanced_acc(d, labels)
            if best is None or ba > best[0]:
                best = (ba, tau, d)
        _, tau, decisions = best
    else:
        tau = None
    rej = {"R": [], "H": [], "I": []}
    for p in pairs:
        rej[labels[p]].append(decisions[p])
    top1 = 0
    for q in questions:
        ranked = sorted(names, key=lambda n: -scores[(q.id, n)])
        top1 += int(ranked[0] in q.relevant)
    return {
        "top1": round(top1 / len(questions), 3),
        "reject_I": round(sum(rej["I"]) / max(1, len(rej["I"])), 3),
        "reject_H": round(sum(rej["H"]) / max(1, len(rej["H"])), 3),
        "accept_R": round(1 - sum(rej["R"]) / max(1, len(rej["R"])), 3),
        "balanced_acc": round(balanced_acc(decisions, labels), 3),
        "tau": tau,
    }


def balanced_acc(decisions: dict, labels: dict) -> float:
    tpr = [decisions[p] for p in labels if labels[p] in ("H", "I")]
    tnr = [not decisions[p] for p in labels if labels[p] == "R"]
    return 0.5 * (sum(tpr) / max(1, len(tpr)) + sum(tnr) / max(1, len(tnr)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--threads", type=int, default=3)
    ap.add_argument("--out", default=str(ROOT / "docs" / "experiments" / f"ueb_wrongfile_ablation_{datetime.now():%Y-%m-%d}.json"))
    args = ap.parse_args()

    make_extra_pool()
    cards = load_pool()
    names = [c.name for c in cards]
    by = {c.name: c for c in cards}
    labels = {(q.id, n): gold(q, n) for q in QUESTIONS for n in names}
    counts = {k: sum(1 for v in labels.values() if v == k) for k in "RHI"}
    print(f"havuz: {len(cards)} dosya, {len(QUESTIONS)} soru, çiftler R/H/I = {counts}")

    results: dict[str, dict] = {}
    timings: dict[str, float] = {}
    details: dict[str, dict] = {}

    def run_arm(name: str, fn, decisions=None):
        t0 = time.perf_counter()
        sc = {(q.id, c.name): float(fn(q, c)) for q in QUESTIONS for c in cards}
        timings[name] = round(time.perf_counter() - t0, 3)
        results[name] = evaluate(sc, decisions, labels, QUESTIONS, names)
        return sc

    run_arm("A_filename", arm_filename)
    run_arm("B_schema", arm_schema)

    # D BM25
    idx = Bm25Index()
    idx.index([Candidate(id=c.name, text=c.text_full()) for c in cards])
    t0 = time.perf_counter()
    bm = {}
    for q in QUESTIONS:
        hits = {h.id: h.score for h in idx.search(q.text, k=len(cards), require_full_match=False)}
        mx = max(hits.values()) if hits else 1.0
        for c in cards:
            bm[(q.id, c.name)] = (hits.get(c.name, 0.0) / mx) if mx else 0.0
    timings["D_bm25"] = round(time.perf_counter() - t0, 3)
    results["D_bm25"] = evaluate(bm, None, labels, QUESTIONS, names)

    # H sözleşme (deterministik)
    t0 = time.perf_counter()
    hs, hd, hreason = {}, {}, {}
    for q in QUESTIONS:
        for c in cards:
            dec, s, why = contract_check(q, c)
            hs[(q.id, c.name)] = s
            hd[(q.id, c.name)] = dec == "reject"
            hreason[(q.id, c.name)] = f"{dec}: {why}"
    timings["H_contract_det"] = round(time.perf_counter() - t0, 3)
    results["H_contract_det"] = evaluate(hs, hd, labels, QUESTIONS, names)
    details["H_contract_det"] = {f"{k[0]}|{k[1]}": v for k, v in hreason.items()}

    # R depodaki ilgi kapısı
    t0 = time.perf_counter()
    rs, rd = {}, {}
    for q in QUESTIONS:
        for c in cards:
            irr, s = arm_repo_gate(q, c)
            rs[(q.id, c.name)] = s
            rd[(q.id, c.name)] = irr
    timings["R_repo_gate"] = round(time.perf_counter() - t0, 3)
    results["R_repo_gate"] = evaluate(rs, rd, labels, QUESTIONS, names)

    settings = load_settings()
    # C/E/F embedding
    try:
        from kkb_agent.adapters.mia_embedder import MiaEmbedder
        emb = MiaEmbedder(base_url=settings.llm_base_url, api_key=settings.llm_api_key, model=settings.embedding_model or "")
        t0 = time.perf_counter()
        qv = np.asarray(emb.embed([q.text for q in QUESTIONS]), dtype=np.float32)
        mv = np.asarray(emb.embed([c.text_meta() for c in cards]), dtype=np.float32)
        fv = np.asarray(emb.embed([c.text_full() for c in cards]), dtype=np.float32)
        t_emb = time.perf_counter() - t0
        cs, es, fs = {}, {}, {}
        for i, q in enumerate(QUESTIONS):
            qy = years_in(q.text)
            for j, c in enumerate(cards):
                cs[(q.id, c.name)] = cos(qv[i], mv[j])
                fs[(q.id, c.name)] = cos(qv[i], fv[j])
                pok = 1.0 if not (qy and c.years) or any(c.years[0] <= y <= c.years[1] for y in qy) else 0.0
                es[(q.id, c.name)] = cs[(q.id, c.name)] * pok
        timings["C_embed_meta"] = timings["E_embed_period"] = timings["F_embed_full"] = round(t_emb / 3, 3)
        results["C_embed_meta"] = evaluate(cs, None, labels, QUESTIONS, names)
        results["E_embed_period"] = evaluate(es, None, labels, QUESTIONS, names)
        results["F_embed_full"] = evaluate(fs, None, labels, QUESTIONS, names)
        # hard-negative marj analizi: Q01/Q10 için R-max vs H-max kosinüs farkı
        margins = {}
        for i, q in enumerate(QUESTIONS):
            r = [fs[(q.id, n)] for n in names if labels[(q.id, n)] == "R"]
            h = [fs[(q.id, n)] for n in names if labels[(q.id, n)] == "H"]
            if r and h:
                margins[q.id] = {"R_mean": round(statistics.mean(r), 3), "H_mean": round(statistics.mean(h), 3),
                                 "R_min": round(min(r), 3), "H_max": round(max(h), 3)}
        details["F_margins"] = margins
    except Exception as exc:  # noqa: BLE001
        print("embedding kolu atlandı:", exc)

    # G LLM yargıç (+ I: H kesin değilse G)
    if not args.no_llm:
        from kkb_agent.llm.openai_compat import OpenAICompatClient
        client = OpenAICompatClient(base_url=settings.llm_base_url, api_key=settings.llm_api_key, model=settings.llm_model,
                                    disable_thinking=True)
        pairs = [(q, c) for q in QUESTIONS for c in cards]
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.threads) as ex:
            outs = list(ex.map(lambda qc: llm_judge(client, *qc), pairs))
        t_llm = time.perf_counter() - t0
        gs, gd, greason = {}, {}, {}
        for (q, c), (v, why) in zip(pairs, outs):
            key = (q.id, c.name)
            gs[key] = {"evet": 1.0, "kısmen": 0.5, "hayır": 0.0}[v]
            gd[key] = v == "hayır"
            greason[f"{q.id}|{c.name}"] = f"{v}: {why[:140]}"
        timings["G_llm_judge"] = round(t_llm, 1)
        results["G_llm_judge"] = {**evaluate(gs, gd, labels, QUESTIONS, names), "llm_calls": len(pairs)}
        details["G_llm_judge"] = greason
        # I: H → (partial ise) G
        is_, id_, calls = {}, {}, 0
        for q in QUESTIONS:
            for c in cards:
                key = (q.id, c.name)
                dec = hreason[key].split(":")[0]
                if dec == "partial":
                    calls += 1
                    is_[key] = 0.5 * gs[key] + 0.5 * hs[key]
                    id_[key] = gd[key]
                else:
                    is_[key] = hs[key]
                    id_[key] = hd[key]
        results["I_H_then_G"] = {**evaluate(is_, id_, labels, QUESTIONS, names), "llm_calls": calls}
        timings["I_H_then_G"] = round(timings["H_contract_det"] + t_llm * calls / max(1, len(pairs)), 1)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pool": names, "pairs": counts, "questions": [q.__dict__ | {"relevant": sorted(q.relevant), "hard": sorted(q.hard)} for q in QUESTIONS],
               "results": results, "timings_s": timings, "details": details}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("\n| kol | top-1 | I'yi ret | H'yi ret | R'yi kabul | dengeli doğruluk | τ | süre (s) | LLM |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for k, v in results.items():
        print(f"| {k} | {v['top1']} | {v['reject_I']} | {v['reject_H']} | {v['accept_R']} | {v['balanced_acc']} | "
              f"{v.get('tau') if v.get('tau') is not None else '—'} | {timings.get(k, '—')} | {v.get('llm_calls', 0)} |")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
