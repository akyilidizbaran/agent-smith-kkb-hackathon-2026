"""Deney E7 — bir PDF'ten veri çıkarmanın iki yolunu aynı belge üzerinde karşılaştırır.

    A) METİN KATMANI — PDF'in gömülü metnini PyMuPDF ile okumak (deterministik, model çağrısı yok)
    B) OCR — sayfayı görsele çevirip Unlimited-OCR'a okutmak (taranmış belgelerde tek yol)

Bu sürüm, ekibin ilk deney_ocr.py taslağına üç düzeltme getirir:
  1. Rakam yoğunluğu metriği <|det|>…<|/det|> koordinat bloklarını saymaz (OCR lehine şişmeyi önler).
  2. --bekle değeri binlik/ondalık ayraçlardan bağımsız aranır ("2.450" ≈ "2450" ≈ "2,450").
  3. --coklu-gorsel testi 3 görselin kabulünü VE 4. görselin reddini ayrı ayrı ölçer.

OCR çağrısı MIA Hackathon Rehberi'ne birebir uyar: önce image_url blokları, sonra
"<image>\\ndocument parsing"; extra_body skip_special_tokens=False + vllm_xargs; window_size
tek görselde 128, çoklu görselde 1024; max_tokens 8192; temperature 0; yalnızca base64.

KULLANIM
    python scripts/deney_ocr.py --pdf data/adhoc/altin.pdf
    python scripts/deney_ocr.py --pdf data/adhoc/altin.pdf --sayfa 2 --bekle "2.450" --dpi 200
    python scripts/deney_ocr.py --pdf data/adhoc/altin.pdf --coklu-gorsel
    python scripts/deney_ocr.py --pdf data/adhoc/altin.pdf --rapor docs/experiments/E7_ocr.md
Anahtar: .env içindeki LLM_API_KEY (dosya .gitignore'da). Hiçbir çıktıda basılmaz.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import sys
import time
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    sys.exit("openai paketi yok:  pip install openai")
try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("pymupdf paketi yok:  pip install pymupdf")

for _stream in (sys.stdout, sys.stderr):  # Windows konsolu (cp1254) kutu çizgilerini basamıyor
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

OCR_MODEL_VARSAYILAN = "kkbhackathon2026/Unlimited-OCR"
BASE_URL_VARSAYILAN = "https://mia.csp.kloudeks.com/v1"
OCR_PROMPT = "<image>\ndocument parsing"
WINDOW_TEK, WINDOW_COKLU, NGRAM_SIZE = 128, 1024, 35
DET_RE = re.compile(r"<\|det\|>.*?<\|/det\|>", re.S)
REF_RE = re.compile(r"<\|ref\|>(.*?)<\|/ref\|>", re.S)

_GIZLI: list[str] = []


def env_yukle(yol: str) -> bool:
    dosya = Path(yol)
    if not dosya.exists():
        return False
    for satir in dosya.read_text(encoding="utf-8-sig").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#") or "=" not in satir:
            continue
        ad, _, deger = satir.partition("=")
        deger = deger.strip().strip('"').strip("'")
        if deger:
            os.environ.setdefault(ad.strip(), deger)
    return True


def temizle(metin: str) -> str:
    for g in _GIZLI:
        if g and g in metin:
            metin = metin.replace(g, "<ANAHTAR-GIZLENDI>")
    return metin


RAPOR: list[str] = []


def yaz(*parcalar: object) -> None:
    s = temizle(" ".join(str(p) for p in parcalar))
    print(s)
    RAPOR.append(s)


# ---------------------------------------------------------------- Yol A
def metin_katmani(pdf: str, sayfa_no: int) -> tuple[str, list[list[str]], float]:
    t0 = time.perf_counter()
    belge = fitz.open(pdf)
    sayfa = belge[sayfa_no - 1]
    duz = sayfa.get_text().strip()
    tablolar: list[list[str]] = []
    try:
        for tablo in sayfa.find_tables().tables:
            for satir in tablo.extract():
                tablolar.append(["" if h is None else str(h) for h in satir])
    except Exception:  # noqa: BLE001
        pass
    belge.close()
    return duz, tablolar, time.perf_counter() - t0


# ---------------------------------------------------------------- Yol B
def sayfa_gorseli(pdf: str, sayfa_no: int, dpi: int) -> tuple[bytes, int, int]:
    belge = fitz.open(pdf)
    pix = belge[sayfa_no - 1].get_pixmap(dpi=dpi)
    png = pix.tobytes("png")
    w, h = pix.width, pix.height
    belge.close()
    return png, w, h


def data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def ocr(istemci: OpenAI, model: str, gorseller: list[bytes]) -> tuple[str, float, dict]:
    icerik: list[dict] = [{"type": "image_url", "image_url": {"url": data_uri(g)}} for g in gorseller]
    icerik.append({"type": "text", "text": OCR_PROMPT})
    window = WINDOW_COKLU if len(gorseller) > 1 else WINDOW_TEK
    t0 = time.perf_counter()
    y = istemci.chat.completions.create(
        model=model, messages=[{"role": "user", "content": icerik}], temperature=0.0, max_tokens=8192,
        extra_body={"skip_special_tokens": False, "vllm_xargs": {"ngram_size": NGRAM_SIZE, "window_size": window}},
    )
    sure = time.perf_counter() - t0
    metin = (y.choices[0].message.content or "").strip()
    kullanim = {"prompt": y.usage.prompt_tokens, "completion": y.usage.completion_tokens} if y.usage else {}
    return metin, sure, kullanim


def ocr_temiz(metin: str) -> str:
    """<|det|> koordinatlarını at, <|ref|> içeriğini düz metne indir."""
    metin = DET_RE.sub("", metin)
    metin = REF_RE.sub(r"\1", metin)
    return metin.replace("<|ref|>", "").replace("<|/ref|>", "")


# ---------------------------------------------------------------- metrikler
def rakam_yogunlugu(metin: str) -> int:
    return sum(ch.isdigit() for ch in metin)


def sayi_normalize(s: str) -> str:
    return re.sub(r"[.,\s]", "", s)


def bekle_var_mi(bekle: str, metin: str) -> bool:
    if bekle in metin:
        return True
    hedef = sayi_normalize(bekle)
    return bool(hedef) and hedef in sayi_normalize(metin)


def kirp(metin: str, satir: int = 18) -> str:
    satirlar = [s for s in metin.splitlines() if s.strip()]
    gosterilen = satirlar[:satir]
    kalan = len(satirlar) - len(gosterilen)
    out = "\n".join("    │ " + s[:110] for s in gosterilen)
    if kalan > 0:
        out += f"\n    │ … ({kalan} satır daha)"
    return out or "    │ (boş)"


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description="E7: PDF metin katmanı vs OCR")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--env", default=".env")
    ap.add_argument("--sayfa", type=int, default=1)
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--bekle", default=None)
    ap.add_argument("--coklu-gorsel", action="store_true", help="3 görsel kabul + 4 görsel red testi")
    ap.add_argument("--rapor", default=None, help="markdown rapor yolu (opsiyonel)")
    arg = ap.parse_args()

    if not os.path.exists(arg.pdf):
        sys.exit(f"PDF bulunamadı: {arg.pdf}")
    env_bulundu = env_yukle(arg.env)
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("MIA_API_KEY")
    if not api_key:
        sys.exit(f"LLM_API_KEY yok (aranan dosya: {arg.env}, {'var' if env_bulundu else 'YOK'}).")
    _GIZLI.append(api_key)
    istemci = OpenAI(base_url=os.environ.get("LLM_BASE_URL", BASE_URL_VARSAYILAN), api_key=api_key, timeout=300.0)
    model = os.environ.get("OCR_MODEL", OCR_MODEL_VARSAYILAN)

    belge = fitz.open(arg.pdf)
    toplam = belge.page_count
    belge.close()
    if arg.sayfa > toplam:
        sys.exit(f"Belgede {toplam} sayfa var.")

    yaz("=" * 74)
    yaz("E7 — metin katmanı mı, OCR mı?")
    yaz("=" * 74)
    yaz(f"  belge : {arg.pdf} ({toplam} sayfa) · sayfa {arg.sayfa} · model {model}")

    # ---- A
    yaz("\n" + "-" * 74 + "\nYOL A — METİN KATMANI\n" + "-" * 74)
    a_metin, a_tablolar, a_sure = metin_katmani(arg.pdf, arg.sayfa)
    yaz(f"  süre {a_sure * 1000:.0f} ms · karakter {len(a_metin)} · rakam {rakam_yogunlugu(a_metin)} · tablo satırı {len(a_tablolar)}")
    yaz("  metin:\n" + kirp(a_metin))
    if a_tablolar:
        yaz("  tespit edilen tablo (ilk 8 satır):")
        for s in a_tablolar[:8]:
            yaz("    │ " + " | ".join(h[:22] for h in s))
    a_bos = len(a_metin) < 40

    # ---- B
    yaz("\n" + "-" * 74 + "\nYOL B — OCR (Unlimited-OCR)\n" + "-" * 74)
    png, w, h = sayfa_gorseli(arg.pdf, arg.sayfa, arg.dpi)
    yaz(f"  görsel {w}x{h}px · {len(png) / 1024:.0f} KB · {arg.dpi} dpi · gönderiliyor…")
    try:
        b_ham, b_sure, b_kul = ocr(istemci, model, [png])
    except Exception as hata:  # noqa: BLE001
        yaz(f"  ! OCR ÇAĞRISI BAŞARISIZ: {type(hata).__name__}: {temizle(str(hata))[:400]}")
        b_ham, b_sure, b_kul = "", 0.0, {}
    b_metin = ocr_temiz(b_ham)
    yaz(f"  süre {b_sure:.1f} s · ham karakter {len(b_ham)} · temiz karakter {len(b_metin)} · rakam (temiz) {rakam_yogunlugu(b_metin)}")
    yaz(f"  yerleşim etiketleri: {b_ham.count('<|ref|>')} ref · {b_ham.count('<|det|>')} det · token {b_kul}")
    if not b_ham:
        yaz("  ! BOŞ YANIT — prompt/extra_body formatını rehberle karşılaştır")
    yaz("  metin (temiz):\n" + kirp(b_metin))

    # ---- 3 görsel sınırı
    if arg.coklu_gorsel:
        yaz("\n" + "-" * 74 + "\nEK TEST — çağrı başına görsel sınırı\n" + "-" * 74)
        n3 = min(3, toplam)
        gorseller = [sayfa_gorseli(arg.pdf, i + 1, arg.dpi)[0] for i in range(n3)]
        try:
            c_ham, c_sure, _ = ocr(istemci, model, gorseller)
            yaz(f"  {n3} görsel: ✓ kabul · {c_sure:.1f} s · {len(ocr_temiz(c_ham))} temiz karakter")
        except Exception as hata:  # noqa: BLE001
            yaz(f"  {n3} görsel: ✗ {type(hata).__name__}: {temizle(str(hata))[:200]}")
        if toplam >= 4 or n3 == 3:
            dort = gorseller + [gorseller[0]] if toplam < 4 else [sayfa_gorseli(arg.pdf, i + 1, arg.dpi)[0] for i in range(4)]
            try:
                _, d_sure, _ = ocr(istemci, model, dort)
                yaz(f"  4 görsel: kabul edildi ({d_sure:.1f} s) — rehberdeki 3 sınırı sunucuda zorlanmıyor")
            except Exception as hata:  # noqa: BLE001
                yaz(f"  4 görsel: ✗ reddedildi — {type(hata).__name__}: {temizle(str(hata))[:160]}")

    # ---- karar
    yaz("\n" + "=" * 74 + "\nKARAR\n" + "=" * 74)
    if arg.bekle:
        yaz(f"  aranan {arg.bekle!r}: metin katmanı {'VAR' if bekle_var_mi(arg.bekle, a_metin) else 'YOK'} · OCR {'VAR' if bekle_var_mi(arg.bekle, b_metin) else 'YOK'}")
    if a_bos:
        if len(b_metin) > 40:
            yaz("  Metin katmanı BOŞ, OCR okudu → bu belge için OCR BİRİNCİL yol (PDF → sayfa görseli → OCR → tablo).")
        else:
            yaz("  İki yol da okuyamadı → belge sorunlu ya da görsel çözünürlük düşük; --dpi 200 ile tekrar dene.")
    else:
        oran = rakam_yogunlugu(b_metin) / max(1, rakam_yogunlugu(a_metin))
        yaz(f"  Metin katmanı DOLU: {a_sure * 1000:.0f} ms vs OCR {b_sure:.1f} s; OCR rakam/metin rakam = {oran:.2f}")
        yaz("  → METİN KATMANI BİRİNCİL, OCR yalnızca metin katmanı boş dönerse (fallback).")

    if arg.rapor:
        p = Path(arg.rapor)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# E7 — metin katmanı vs OCR\n\n```text\n" + "\n".join(RAPOR) + "\n```\n", encoding="utf-8")
        print(f"\nrapor: {p}")


if __name__ == "__main__":
    main()
