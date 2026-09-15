"""UEB "sonra" (çevrimdışı) — önerilen deterministik denetimler kaydedilmiş baseline koşusuna uygulanır.

Harness'a bağlanmadan, LLM çağırmadan: her vaka için hangi denetim tetiklenirdi? Elle etiketlenmiş
SILENT/LATE vakalarında en az bir denetim tetiklenmeli; kontrol (D) ve SAFE vakalarında tetiklenmemeli
(yanlış pozitif). Bu, mimari değişikliğin ölçülmüş "beklenen kazancı"dır — uçtan uca kanıt DEĞİLDİR.

Denetimler (hepsi saf fonksiyon, hepsi generic; alan sözlüğü yalnız kavram eşlemede):
  G1 fitness_gate        soru gereksinimi × dosya kavramları (ablation H kolu) — dosya yüklenmeden ÖNCE
  G2 table_quality       eksik dönem, mükerrer (tarih), toplam satırı, küçük örneklem, birim yok, etiket-değer makullüğü
  G3 question_preflight  katalogda olmayan ölçüm/kırılım, frekans, tahmin niyeti, para birimi, reel/deflatör
  G4 premise_check       "X düştüğü/arttığı için" → X serisinin sorudaki yıldaki yönü (DB'den) → DESTEKLİYOR/ÇELİŞİYOR
  G5 claim_cell          cevaptaki (dönem, sayı) çifti DB'de o dönemde var mı (yanlış hücre)
  G6 range_claim         cevaptaki "kapsam/dönem A → B" beyanı tablonun gerçek aralığıyla uyuşuyor mu

Kullanım (repo kökünden):  python scripts/ueb_after_offline.py --baseline docs/experiments/ueb_baseline_2026-09-14_0054.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "agent-core" / "src"))
sys.path.insert(0, str(HERE))
from ueb_wrongfile_ablation import FileCard, contract_check, load_pool, Q  # noqa: E402
from ueb_cases import BY_ID  # noqa: E402
from ueb_run import DB_VARIANTS  # noqa: E402

MONTHS = {"ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5, "haziran": 6, "temmuz": 7,
          "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9, "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
          "oca": 1, "şub": 2, "mar": 3, "nis": 4, "may": 5, "haz": 6, "tem": 7, "ağu": 8, "eyl": 9, "eki": 10, "kas": 11, "ara": 12}
_NUM = re.compile(r"(?<![\w.,])\d{1,3}(?:\.\d{3})+(?:,\d+)?(?!\w)|(?<![\w.,])\d{4,}(?:[.,]\d+)?(?!\w)")


def tr_num(raw: str) -> float | None:
    s = raw.replace(".", "").replace(",", ".") if "," in raw else (raw.replace(".", "") if re.fullmatch(r"\d{1,3}(\.\d{3})+", raw) else raw)
    try:
        return float(s)
    except ValueError:
        return None


# ------------------------------------------------------------------ G2 tablo kalitesi
def table_quality(frame: pd.DataFrame, card: FileCard, question: str) -> list[str]:
    flags: list[str] = []
    m = card.mapping
    if m is not None:
        dcol = m.observation_date_column
    else:
        # Toleranslı eşleme: profilci %100 ister (toplam satırı bozar); burada ≥%80 tarih ayrışan kolon yeter.
        # Yıl kolonu (yil/yıl/year) yıllık tablodur: boşluk/mükerrer denetimi anlamsız, "bulunamadı" da değil.
        year_col = next((c for c in frame.columns if re.fullmatch(r"y[ıi]l|year", str(c), re.I)), None)
        if year_col is not None:
            return flags
        ratios = {c: pd.to_datetime(frame[c], errors="coerce").notna().mean() for c in frame.columns}
        dcol = max(ratios, key=ratios.get)
        if ratios[dcol] < 0.8:
            return ["tarih+değer kolonu bulunamadı (okunamayan/yanlış sayfa)"]
    dates = pd.to_datetime(frame[dcol], errors="coerce")
    bad = frame[dates.isna()]
    if len(bad):
        vals = [str(v) for v in bad[dcol].head(3)]
        flags.append(f"tarih kolonunda tarih olmayan satır: {vals} (toplam/dipnot satırı olabilir)")
    good = dates.dropna().sort_values()
    if len(good) >= 3:
        gaps = good.diff().dt.days.dropna()
        med = gaps.median()
        if med <= 31 and (gaps > 45).any():
            missing = int(round(((gaps[gaps > 45] / 30.4).round() - 1).sum()))
            flags.append(f"eksik dönem: ardışık tarih farkı > frekans ({missing} ay boşluk)")
        dup = good[good.duplicated()].dt.strftime("%Y-%m").unique().tolist()
        if dup:
            flags.append(f"mükerrer dönem: {dup}")
    yrs = {int(y) for y in re.findall(r"\b(20[0-9]{2})\b", question)}
    if yrs and len(good) and re.search(r"trend|yıllık|büyüme|değişim", question, re.I):
        for y in yrs:
            n_y = int((good.dt.year == y).sum())
            if 0 < n_y < 12 and card.freq == "monthly":
                flags.append(f"kısmi yıl: {y} için {n_y} ay var")
    if len(frame) <= 6 and re.search(r"trend|yıl", question, re.I):
        flags.append(f"küçük örneklem: {len(frame)} satır")
    # birim: başlık/dosya adında birim ipucu yoksa
    if not re.search(r"milyon|bin|mn|th|try|tl|%|yüzde|pct|adet|endeks|index|oran", " ".join(card.headers) + " " + card.stem_name, re.I):
        if re.search(r"milyon|milyar|bin tl|birim|kaç tl", question, re.I):
            flags.append("birim beyanı yok: soru birim istiyor, dosyada birim ipucu yok")
    # etiket-değer makullüğü
    for col, med_v in card.numeric_median.items():
        if re.search(r"faiz|oran|rate|yüzde|pct", col, re.I) and abs(med_v) > 1000:
            flags.append(f"etiket-değer uyuşmazlığı: '{col}' oran gibi adlandırılmış, medyan {med_v:,.0f}")
        if re.search(r"oran|ratio", col, re.I) and 0 < abs(med_v) < 0.05 and re.search(r"yüzde|%", question, re.I):
            flags.append(f"oran/yüzde belirsizliği: '{col}' medyan {med_v:.4f} (oran olarak okunursa %{med_v*100:.2f})")
    return flags


# ------------------------------------------------------------------ G3 soru ön-koşulları (katalog: seed tek tablo)
CATALOG_MEASURES = {"bakiye"}          # seed'in sunduğu ölçüm kavramları (kataloğun measure semantic_type'ından türetilir)
CATALOG_DIMS = {"kalem", "tp_yp"}      # kırılımlar
CATALOG_FREQ = "monthly"


def question_preflight(question: str, tools: set[str]) -> list[str]:
    q = question.casefold().replace("i̇", "i")
    flags = []
    need = []
    if re.search(r"faiz oran|faiz\b", q) and "faiz" not in CATALOG_MEASURES:
        need.append("faiz oranı")
    if re.search(r"müşteri sayısı|kişi sayısı|adet", q):
        need.append("müşteri/adet")
    if re.search(r"yaş|cinsiyet|demograf", q):
        need.append("demografik kırılım")
    if re.search(r"\breel\b|enflasyondan arınd|deflat", q):
        need.append("deflatör (TÜFE)")
    if re.search(r"dolar|euro|usd|eur", q):
        need.append("kur/para birimi")
    if need:
        flags.append("katalogda olmayan ölçüm istendi: " + ", ".join(need))
    if re.search(r"istanbul|ankara|izmir|il baz|ilindeki|ilde", q):
        flags.append("il kırılımı istendi; katalogda il boyutu yok")
    if re.search(r"katılım bank|kamu bank|özel bank|banka grub", q):
        flags.append("banka grubu kırılımı istendi; katalogda yok")
    if re.search(r"haftalık|günlük", q) and CATALOG_FREQ == "monthly":
        flags.append("istenen frekans katalogdan ince (aylık veri)")
    if re.search(r"tahmin|öngörü|projeksiyon|forecast", q) and not tools & {"forecast"}:
        flags.append("tahmin istendi; tahmin aracı yok → yetki dışı hesap")
    if re.search(r"\bkaç puan\b", q) and re.search(r"bakiye", q):
        flags.append("'puan' bir bakiye için tanımsız; yüzde değişim verilecek")
    if re.search(r"^\s*(2025'te|2024'te)?\s*kredi bakiyesi", q) or re.fullmatch(r".*\bkredi bakiyesi ne kadar\??", q):
        flags.append("belirsiz kalem: 'kredi' 60+ kalemle eşleşiyor → netleştir ya da seçimi beyan et")
    return flags


# ------------------------------------------------------------------ G4 öncül
_PREMISE = re.compile(r"(?P<ent>konut kredi\w*|taşıt kredi\w*|ihtiyaç kredi\w*|kredi kart\w*)\s*(?:bakiyesi)?\s*"
                      r"(?P<dir>düştüğü|azaldığı|arttığı|yükseldiği|geriledi|arttı)", re.I)
KALEM = {"konut": "Tüketici Kredileri - Konut", "taşıt": "Tüketici Kredileri - Taşıt", "ihtiyaç": "Tüketici Kredileri - İhtiyaç"}


def premise_check(question: str, db: Path) -> list[str]:
    out = []
    yrs = re.findall(r"\b(20[0-9]{2})\b", question)
    m = _PREMISE.search(question)
    m2 = re.search(r"(20\d{2})'?te\s+(taşıt|konut|ihtiyaç) kredi\w*\s+neden\s+(arttı|azaldı|geriledi|düştü)", question, re.I)
    if not m and not m2:
        return out
    ent = (m.group("ent") if m else m2.group(2)).casefold()
    claimed = (m.group("dir") if m else m2.group(3)).casefold()
    year = int(yrs[0]) if yrs else None
    key = next((k for k in KALEM if k in ent), None)
    if key is None or year is None:
        return out
    con = duckdb.connect(str(db), read_only=True)
    rows = con.execute("SELECT donem, toplam FROM bddk_aylik_krediler WHERE kalem = ? AND EXTRACT(year FROM donem) = ? ORDER BY donem",
                       [KALEM[key], year]).fetchall()
    con.close()
    if len(rows) < 2:
        return [f"öncül doğrulanamadı: {KALEM[key]} {year} verisi yok"]
    first, last = rows[0][1], rows[-1][1]
    actual = "arttı" if last > first else "düştü"
    claimed_dir = "düştü" if re.search(r"düş|azal|geril", claimed) else "arttı"
    verdict = "DESTEKLİYOR" if actual == claimed_dir else "ÇELİŞİYOR"
    out.append(f"öncül [{verdict}]: '{KALEM[key]} {year} {claimed_dir}' — veri: {first:,.0f} → {last:,.0f} ({actual})")
    return out


# ------------------------------------------------------------------ G5 iddia-hücre
def claim_cell(answer: str, db: Path) -> list[str]:
    """Satırda 'Aralık 2025 ... 642.144' gibi (dönem, sayı) çifti varsa DB'de o dönemde o sayı var mı?"""
    out = []
    con = duckdb.connect(str(db), read_only=True)
    period_re = re.compile(r"\b(ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)\s+(20\d{2})\b|\b(20\d{2})-(0[1-9]|1[0-2])\b", re.I)
    for line in (answer or "").splitlines():
        periods = []
        for mm in period_re.finditer(line):
            if mm.group(1):
                periods.append((mm.start(), int(mm.group(2)), MONTHS[mm.group(1).casefold()]))
            else:
                periods.append((mm.start(), int(mm.group(3)), int(mm.group(4))))
        if not periods:
            continue
        is_row = line.strip().startswith("|")
        big = [nm for nm in _NUM.finditer(line) if (tr_num(nm.group(0)) or 0) >= 1000 and not (1900 <= (tr_num(nm.group(0)) or 0) <= 2100)]
        # Düz yazıda birden çok dönem/sayı bir cümlede karışabilir ("Ocak'ta X, Aralık'ta Y"); yalnız
        # tablo satırında ya da tek dönem + tek sayı satırında karar verilir (ölçüldü: A15/D05 yanlış pozitif).
        if not is_row and (len(periods) != 1 or len(big) != 1):
            continue
        for nm in big:
            raw = nm.group(0)
            v = tr_num(raw)
            if v is None or v < 1000 or (1900 <= v <= 2100 and v.is_integer()):
                continue
            # Sayıyı satırdaki EN YAKIN (önce solundaki) dönemle eşle: tablo satırında dönem sayıdan önce gelir.
            left = [p for p in periods if p[0] < nm.start()]
            _, y, mo = (left[-1] if left else min(periods, key=lambda p: abs(p[0] - nm.start())))
            hits = con.execute("SELECT DISTINCT donem FROM bddk_aylik_krediler WHERE abs(toplam - ?) < 0.5 OR abs(tp - ?) < 0.5 OR abs(yp - ?) < 0.5",
                               [v, v, v]).fetchall()
            if not hits:
                continue   # DB'de yok: grounding'in işi (türetilmiş sayı olabilir)
            db_periods = {(d[0].year, d[0].month) for d in hits}
            if (y, mo) not in db_periods:
                out.append(f"yanlış hücre: satırda {y}-{mo:02d} ile {raw} yan yana; {raw} DB'de {sorted(db_periods)[:3]} dönemlerinde")
    con.close()
    return out


# ------------------------------------------------------------------ G6 aralık beyanı
def range_claim(answer: str, frame: pd.DataFrame | None, card: FileCard | None) -> list[str]:
    if card is None or card.years is None or card.mapping is None:
        return []
    dates = pd.to_datetime(frame[card.mapping.observation_date_column], errors="coerce").dropna()
    if dates.empty:
        return []
    lo, hi = dates.min(), dates.max()
    out = []
    for m in re.finditer(r"(20\d{2})-(0[1-9]|1[0-2])\s*(?:→|-|–|ile)\s*(20\d{2})-(0[1-9]|1[0-2])", answer or ""):
        a = pd.Timestamp(int(m.group(1)), int(m.group(2)), 1); b = pd.Timestamp(int(m.group(3)), int(m.group(4)), 1)
        if (a.year, a.month) != (lo.year, lo.month) or (b.year, b.month) != (hi.year, hi.month):
            out.append(f"aralık beyanı {m.group(0)} ≠ tablo {lo:%Y-%m}→{hi:%Y-%m}")
    for m in re.finditer(r"(ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)\s*(20\d{2})?\s*[–\-]\s*(ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)\s+(20\d{2})", answer or "", re.I):
        b_y, b_m = int(m.group(4)), MONTHS[m.group(3).casefold()]
        if (b_y, b_m) != (hi.year, hi.month):
            out.append(f"aralık beyanı '{m.group(0)}' ≠ tablo son dönem {hi:%Y-%m}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--out", default=str(ROOT / "docs" / "experiments" / "ueb_after_offline_2026-09-14.json"))
    args = ap.parse_args()
    runs = json.load(open(args.baseline, encoding="utf-8"))
    cards = {c.name: c for c in load_pool()}
    report = []
    for r in runs:
        case = BY_ID.get(r["id"])
        if case is None or "error" in r:
            continue
        fired: dict[str, list[str]] = {}
        db = DB_VARIANTS[case.db]
        q = case.queries[-1]
        fm = re.search(r"\.\./incoming/ueb/([\w\.]+)", q)
        card = cards.get(fm.group(1)) if fm else None
        if card is not None:
            dec, score, why = contract_check(Q(r["id"], q, set(), set()), card)
            if dec != "accept":
                fired["G1_fitness_gate"] = [f"{dec}: {why}"]
            tq = table_quality(card.frame, card, q)
            if tq:
                fired["G2_table_quality"] = tq
            rc = range_claim(r.get("answer", ""), card.frame, card)
            if rc:
                fired["G6_range_claim"] = rc
        else:
            pf = question_preflight(q, set(r.get("tools", [])))
            if pf:
                fired["G3_question_preflight"] = pf
            pc = premise_check(q, db)
            if pc:
                fired["G4_premise_check"] = pc
            cc = claim_cell(r.get("answer", ""), db)
            if cc:
                fired["G5_claim_cell"] = cc
        report.append({"id": r["id"], "expected": case.expected, "auto_verdict": r.get("verdict"), "fired": fired})
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for row in report:
        keys = ", ".join(f"{k}[{len(v)}]" for k, v in row["fired"].items()) or "—"
        print(f"{row['id']:32} {row['expected']:8} {row['auto_verdict']:9} {keys}")
        for k, v in row["fired"].items():
            for line in v:
                print(f"      {k}: {line[:150]}")
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
