"""D04/D05 (ADR-0069): tam sıfırlamanın kapsamı yapılandırmadan, sonucu hedef hedef ve doğrulanmış; katalog varsayılan boş.

Her şey geçici kökte; asıl data/ dizinine dokunulmaz."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.web_app import ResetPaths, create_app, execute_full_reset, plan_reset  # noqa: E402
from tests.test_m04_profil import _factory_recording  # noqa: E402

REPO_DATA = Path(__file__).resolve().parents[2] / "data"


def _world(tmp_path: Path):
    data = tmp_path / "data"
    for d in ("raw", "bronze", "charts", "cache/embeddings", "incoming/uploads/abc"):
        (data / d).mkdir(parents=True)
    (data / "charts" / "old.png").write_bytes(b"png")
    (data / "cache" / "embeddings" / "v.npy").write_bytes(b"x")
    (data / "incoming" / "uploads" / "abc" / "f.csv").write_text("a")
    (data / "incoming" / "jury.csv").write_text("korunur: izinli kök, oturum yüklemesi değil")
    db = data / "lakehouse.duckdb"
    db.write_bytes(b"x")
    paths = ResetPaths(data_root=data, db_path=db, upload_root=data / "incoming" / "uploads", chart_dir=data / "charts",
                       cache_dir=data / "cache")
    return data, db, paths


def _schema_only_bootstrap(db: Path, series: int = 0, mode: str = "none"):
    def boot(catalog_mode: str = "none"):
        con = duckdb.connect(str(db))
        con.execute("CREATE SCHEMA IF NOT EXISTS meta")
        con.execute("CREATE TABLE IF NOT EXISTS meta.series (series_id VARCHAR)")
        con.execute("CREATE TABLE IF NOT EXISTS meta.lakehouse_setting (key VARCHAR PRIMARY KEY, value VARCHAR, updated_at TIMESTAMP)")
        for i in range(series):
            con.execute("INSERT INTO meta.series VALUES (?)", [f"bddk:{i}"])
        con.execute("INSERT OR REPLACE INTO meta.lakehouse_setting VALUES ('series_catalog', ?, now())", [mode if mode else catalog_mode])
        con.close()
        return 0, f"status: success\ncatalog_mode: {catalog_mode}"
    return boot


def test_kapsam_grafik_ve_onbellegi_icerir_sonuc_hedef_hedef_dogrulanir(tmp_path: Path) -> None:
    # Asıl data/ git'te yok (temiz CI kopyasında hiç yok): koşul "var olmalı" değil, "sıfırlama ona dokunmadı" (PR #3 CI bulgusu).
    repo_data_before = REPO_DATA.exists()
    data, db, paths = _world(tmp_path)
    plan = plan_reset(paths)
    labels = {label for label, _ in plan.targets}
    assert {"veritabanı", "RAW", "Bronze", "oturum yüklemeleri", "grafikler", "önbellek"} <= labels
    report = execute_full_reset(plan, data, bootstrap=_schema_only_bootstrap(db), db_path=db)
    assert report["status"] == "tamamlandı", report
    assert not (data / "charts" / "old.png").exists() and not (data / "cache" / "embeddings" / "v.npy").exists(), "R05: eski grafik kalmaz"
    assert (data / "incoming" / "jury.csv").exists(), "izinli kökteki kullanıcı dosyası oturum yüklemesi değil"
    assert report["verify"]["ok"] and report["verify"]["series"] == 0 and report["verify"]["catalog_mode"] == "none"
    assert {r["status"] for r in report["results"]} <= {"silindi", "zaten yok"}
    assert REPO_DATA.exists() == repo_data_before, "asıl veri köküne dokunulmadı"


def test_silinemeyen_hedef_basari_listesine_girmez_kismi_raporlanir(tmp_path: Path, monkeypatch) -> None:
    data, db, paths = _world(tmp_path)
    real = shutil.rmtree

    def flaky(path, *a, **k):
        if Path(path).name == "charts":
            raise PermissionError("izin yok")
        return real(path, *a, **k)
    monkeypatch.setattr(shutil, "rmtree", flaky)
    report = execute_full_reset(plan_reset(paths), data, bootstrap=_schema_only_bootstrap(db), db_path=db)
    failed = [r["path"] for r in report["failed"]]
    assert report["status"] == "kısmi" and str(data / "charts") in failed and str(data / "charts") not in report["removed"]
    assert (data / "charts" / "old.png").exists()


def test_bootstrap_hatasi_ve_dolu_katalog_basari_sayilmaz(tmp_path: Path) -> None:
    data, db, paths = _world(tmp_path)
    broken = execute_full_reset(plan_reset(paths), data, bootstrap=lambda mode="none": (2, "HATA"), db_path=db)
    assert broken["status"] == "kısmi" and not broken["bootstrap"]["ok"] and not broken["verify"]["ok"]
    data2, db2, paths2 = _world(tmp_path / "ikinci")
    refilled = execute_full_reset(plan_reset(paths2), data2, bootstrap=_schema_only_bootstrap(db2, series=3, mode="default"), db_path=db2)
    assert refilled["status"] == "kısmi" and "beklenen boş" in refilled["verify"]["detail"], "R04: finans kataloğu geri gelirse başarı yok"


def test_veri_koku_disindaki_hedef_sifirlamayi_reddeder(tmp_path: Path) -> None:
    data, db, _ = _world(tmp_path)
    outside_charts = tmp_path / "baska_yer" / "charts"
    outside_charts.mkdir(parents=True)
    (outside_charts / "x.png").write_bytes(b"x")
    paths = ResetPaths(data_root=data, db_path=db, chart_dir=outside_charts)
    plan = plan_reset(paths)
    assert plan.outside and plan.outside[0][1] == outside_charts
    report = execute_full_reset(plan, data, bootstrap=_schema_only_bootstrap(db), db_path=db)
    assert report["status"] == "reddedildi" and db.exists() and (outside_charts / "x.png").exists()


def test_uc_uca_onizleme_katalog_secimi_onaya_bagli_okuyucular_kapanir_oturum_temizlenir(tmp_path: Path) -> None:
    data, db, paths = _world(tmp_path)
    closed: list[str] = []
    boot_modes: list[str] = []
    inner = _schema_only_bootstrap(db)

    def boot(catalog_mode="none"):
        boot_modes.append(catalog_mode)
        return inner(catalog_mode)
    agents: list = []
    factory = _factory_recording(agents)

    def recording_factory(*a, **k):
        agent = factory(*a, **k)

        class Lake:
            def close(self):
                closed.append("close")
        tool = type("T", (), {"lakehouse": Lake(), "name": "lakehouse_query"})()
        registry = getattr(agent, "registry", None)
        if registry is not None and hasattr(registry, "register"):
            try:
                registry.register(tool)
            except Exception:  # noqa: BLE001
                pass
        return agent
    app = create_app(recording_factory, profile="analyst", architect_token="t", reset_paths=paths, bootstrap=boot)
    client = TestClient(app)
    client.post("/api/profile", json={"profile": "architect", "token": "t"})
    preview = client.post("/api/architect/reset", json={}).json()
    assert preview["catalog"] == "bos" and any(r["label"] == "grafikler" for r in preview["target_details"]) and not preview["refused"]
    other = client.post("/api/architect/reset", json={"catalog": "varsayilan"}).json()
    assert other["confirm"] != preview["confirm"], "katalog seçimi onay koduna bağlı"
    stale = client.post("/api/architect/reset", json={"confirm": preview["confirm"]})
    assert stale.status_code == 409 and db.exists(), "önizleme sonrası kapsam değişti: yeniden inceleme"
    fresh = client.post("/api/architect/reset", json={}).json()
    done = client.post("/api/architect/reset", json={"confirm": fresh["confirm"]}).json()
    assert done["status"] == "tamamlandı" and boot_modes == ["none"] and done["agent"]["ok"], done
    assert client.get("/api/answers").json() == []
