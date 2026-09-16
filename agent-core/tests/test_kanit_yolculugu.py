"""ADR-0083: kanıt yolculuğu tek gösterim. Kanıtta olan halkalar durak olur, her tür kendi figürüyle; kopuk halkada durur; 3B yok.

Durak kurucusu (`journeyStops`) arayüzün JS'inde; burada gerçek kanıt yükü şekilleriyle node üzerinde koşturulur (node yoksa atlanır).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from kkb_agent.web_app import STATIC_DIR

HTML = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
KINDS = ("cevap", "tablo", "sql", "hesap", "silver", "bronze", "raw", "url", "web", "belge")
SHA = "07c23d953c98261342a02a521ca2567d807a75102013cd7b28b4a1eb181ff57e"


def _journey_js() -> str:
    start = HTML.index("// ---------------- Kanıt yolculuğu (ADR-0083)")
    return HTML[start:HTML.index('$("btn-journey").addEventListener', start)]


def _helper(name: str) -> str:
    i = HTML.index(f"const {name} = ")
    return HTML[i:re.compile(r"\n(?=\S)").search(HTML, i).start()]


def _stops(evidence: dict, idx: int | None = None) -> list[tuple[str, str, str]]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node yok; durak kurucusu tarayıcı dışında koşturulamıyor")
    helpers = "\n".join(_helper(n) for n in ("esc", "fmtInt", "hostOf", "httpUrl", "fmtWhen", "prettySql", "sqlTables"))
    script = (f"globalThis.window = {{}};\n{helpers}\n{_journey_js()}\n"
              f"process.stdout.write(JSON.stringify(journeyStops({json.dumps(evidence)}, {json.dumps(idx)}).map((s) => [s.kind, s.state, s.status])));")
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30, check=True)
    return [tuple(x) for x in json.loads(out.stdout)]


def _obs(**kw) -> dict:
    return {"series_id": "bddk_finturk:ADANA_KonutKredisi", "entity_id": "bddk:10001", "observation_date": "2026-06-30", "value": 15869789.0,
            "quality_flag": "source_warning", "artifact_sha256": SHA, "vintage_id": f"artifact:{SHA}", "run_id": "375a2950-0ebc-4900-893c-80efff1aad82",
            "fetched_at": "2026-09-14T00:40:00+03:00", "locator": "https://www.bddk.org.tr/BultenFinturk/tr/Home/VeriGetir", "http_status": 200,
            "raw_path": f"/d/raw/bddk_finturk/2026-09-13/{SHA}.json", "bronze_path": f"/d/bronze/x/artifact_sha256={SHA}.parquet",
            "raw_digest_ok": True, "raw_present": True, "bronze_present": True, "chain_state": "tam", **kw}


def _ev(**kw) -> dict:
    return {"numbers": [{"number": 15869789.0, "text": "15.869.789", "column": "konut_kredisi_bin_tl", "row_key": "2026-06-30", "row_index": 0,
                         "matched": True, "sign_warning": False, "period_warning": False, "from_question": False}],
            "columns": [{"column": "konut_kredisi_bin_tl",
                         "sql": "SELECT observation_date, value AS konut_kredisi_bin_tl FROM silver.fact_observation WHERE series_id = 'bddk_finturk:ADANA_KonutKredisi'",
                         "dataset_ids": ["bddk_finturk:ADANA_KonutKredisi"], "sources": ["bddk_finturk — Konut Kredisi, ADANA"],
                         "source_urls": ["https://www.bddk.org.tr/BultenFinTurk"], "executed_at": "2026-09-15T20:17:00", "warnings": []}],
            "observations": [_obs()], "web_sources": [], "artifacts": {}, "table_rows": 8, "observation_count": 1, **kw}


def test_uc_boyutlu_gosterim_yuruyen_karakter_ve_sayi_cipleri_yok() -> None:
    assert "three" not in HTML.lower() and "makeThree" not in HTML and "jsmith" not in HTML and "2,5B" not in HTML
    assert "jchip" not in HTML and "Cevaptaki sayılar" not in HTML, "yolculuk bütün cevabın zinciri (kullanıcı, 16 Eyl)"
    assert not (STATIC_DIR / "vendor" / "three.module.min.js").exists()


def test_her_halka_turunun_figuru_ve_adi_var() -> None:
    js = _journey_js()
    for kind in KINDS:
        assert re.search(rf"\n  {kind}: `", js), f"{kind} figürü yok"
        assert re.search(rf'\n  {kind}: \["', js), f"{kind} adı yok"


def test_hareket_azaltma_dar_ekran_ve_sag_panel_kucuk_zinciri() -> None:
    assert "prefers-reduced-motion" in HTML and "(max-width: 720px)" in HTML
    assert 'id="ev-mini"' in HTML and "renderMini(ev || null)" in HTML


def test_tam_zincirde_kanittaki_yedi_halka_kaynaktan_cevaba_durak_olur() -> None:
    stops = _stops(_ev(), 0)
    assert [s[0] for s in stops] == ["url", "raw", "bronze", "silver", "sql", "tablo", "cevap"], "verinin akışı: kaynak başta, cevap sonda"
    assert all(s[1] == "ok" for s in stops), stops
    assert stops[3][2] == "2026-06-30 · 15.869.789" and stops[0][2] == "bddk.org.tr"


def test_ham_yanit_diskte_yoksa_zincir_raw_halkasinda_kopar() -> None:
    stops = _stops(_ev(observations=[_obs(raw_present=False)]), 0)
    states = {k: st for k, st, _ in stops}
    assert states["bronze"] == "ok" and states["raw"] == "broken"
    kinds = [s[0] for s in stops]
    assert kinds.index("url") < kinds.index("raw") < kinds.index("cevap"), "kopukluktan sonrası cevaba kadar doğrulanamaz"


def test_ozeti_denetlenmemis_ham_yanit_dogrulanmis_sayilmaz() -> None:
    assert dict((k, st) for k, st, _ in _stops(_ev(observations=[_obs(raw_digest_ok=None)]), 0))["raw"] == "broken"


def test_ocr_belgesinde_zincir_uc_durak_ve_uyarili() -> None:
    ev = _ev(columns=[{"column": "tutar", "sql": "web_url /x/uploads/ab12cd34_rapor.pdf tablo#0", "dataset_ids": [], "sources": ["web — rapor.pdf"],
                       "source_urls": [], "executed_at": None, "warnings": []}],
             numbers=[{"number": 4218.0, "text": "4.218", "column": "tutar", "row_key": None, "row_index": 2, "matched": True,
                       "sign_warning": False, "period_warning": False, "from_question": False}],
             observations=[], ocr_unverified=True,
             web_sources=[{"url": "/x/uploads/ab12cd34_rapor.pdf", "sha256": "9c" * 32, "fetched_at": "2026-09-15T21:04:00",
                           "ocr": {"model": "kkbhackathon2026/Unlimited-OCR", "pages": [2], "quality": "orta"}}])
    stops = _stops(ev, 0)
    assert [(k, st) for k, st, _ in stops] == [("belge", "warn"), ("tablo", "ok"), ("cevap", "ok")]


def test_hesaplanmis_tablo_kolonu_kendi_duragini_alir() -> None:
    col = {**_ev()["columns"][0], "sources": ["gold — Dönem eşlemeli birleştirme", "bddk_finturk — Konut Kredisi, ADANA"]}
    kinds = [s[0] for s in _stops(_ev(columns=[col]), 0)]
    assert kinds[kinds.index("sql") - 1] == "hesap" and kinds[0] == "url"


def test_tabloda_olmayan_sayida_zincir_cevapta_kopar() -> None:
    num = {**_ev()["numbers"][0], "matched": False, "from_question": True}
    last = _stops(_ev(numbers=[num]), 0)[-1]
    assert last[:2] == ("cevap", "broken") and last[2] == "sorudan, tabloda yok"


def test_butun_cevap_zinciri_her_gozlemin_dosyasini_denetler() -> None:
    other = _obs(observation_date="2026-03-31", value=14493561.0, artifact_sha256="71" * 32, bronze_present=False)
    stops = _stops(_ev(observations=[_obs(), other], observation_count=2), None)
    states = {k: st for k, st, _ in stops}
    assert states["cevap"] == "ok" and states["bronze"] == "broken"
    one = {k: st for k, st, _ in _stops(_ev(observations=[_obs(), other], observation_count=2), 0)}
    assert one["bronze"] == "ok", "tek sayı yalnız kendi gözlemine bakar"
