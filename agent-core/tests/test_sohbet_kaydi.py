"""ADR-0084: sohbet kaydı. Her sohbet ayrı kaydedilir; uygulama yeniden açılınca son sohbet kaldığı yerden sürer, çalışma alanı yerinde geri gelir."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kkb_agent.conversations import ConversationStore, conversation_title  # noqa: E402
from kkb_agent.core.follow_up import FollowUpContext  # noqa: E402
from kkb_agent.llm.base import ChatMessage  # noqa: E402
from kkb_agent.web_app import STATIC_DIR, ResetPaths, create_app  # noqa: E402
from test_web_app import FakeAgent  # noqa: E402

CSV = ("nufus.csv", b"il,nufus\nAdana,2270\n", "text/csv")


class MemoryAgent(FakeAgent):
    """Gerçek ajan gibi: konuşma hafızası listesi, kayıt defterinde kullanıcı metni ve web adres izinleri."""

    def __init__(self, upload_root: Path) -> None:
        super().__init__()
        self.upload_root = upload_root
        self._history: list[ChatMessage] = []
        self._follow_up_context = FollowUpContext()
        self._follow_up_resolution = None
        self.registry.user_text = ""
        self.registry.sanctioned_locators = set()

    def ask(self, question: str):
        self._follow_up_context = FollowUpContext(metric=question, geography=("Adana",))
        self._history += [ChatMessage(role="user", content=question), ChatMessage(role="assistant", content="cevap")]
        self.registry.user_text = question
        self.registry.sanctioned_locators = {"https://www.bddk.org.tr/x"}
        return super().ask(question)


def _app(tmp_path: Path, made: list, *, store: bool = True):
    def factory(profile: str = "analyst") -> MemoryAgent:
        made.append(MemoryAgent(tmp_path / "incoming"))
        return made[-1]
    return TestClient(create_app(factory, conversations=ConversationStore(tmp_path / "conversations") if store else None))


def test_baslik_ilk_sorudan_dosya_satiri_girmez() -> None:
    assert conversation_title("Bu dosyayı analiz et.\n\nDosya: /srv/incoming/uploads/ab/cd_nufus.csv") == "Bu dosyayı analiz et."
    assert conversation_title("Dosya: /x/y.pdf") == "Dosya analizi"
    long = conversation_title("Adana ilinin konut kredisi bakiyesini son sekiz çeyrek için çeyreklik değişimleriyle birlikte göster")
    assert len(long) == 60 and long.endswith("…")


def test_cevaptan_sonra_kaydedilir_uygulama_yeniden_acilinca_kaldigi_yerden(tmp_path) -> None:
    made: list[MemoryAgent] = []
    client = _app(tmp_path, made)
    client.post("/api/ask", json={"question": "2025 Aralık konut kredisi?"})
    lst = client.get("/api/conversations").json()
    assert lst["persistent"] and [(i["title"], i["count"]) for i in lst["items"]] == [("2025 Aralık konut kredisi?", 1)]
    cid = lst["active"]
    assert (tmp_path / "conversations" / cid / "meta.json").is_file()

    made.clear()
    again = _app(tmp_path, made)                     # sunucu kapandı, yeniden açıldı
    assert again.get("/api/conversations").json()["active"] == cid
    answers = again.get("/api/answers").json()
    assert len(answers) == 1 and answers[0]["text"].startswith("2025 Aralık")
    agent = made[-1]
    assert agent.workspace.has_table and list(agent.workspace.table.columns) == ["donem", "bakiye"], "takip sorusu aynı tabloyla sürer"
    assert [m.content for m in agent._history] == ["2025 Aralık konut kredisi?", "cevap"]
    assert agent._follow_up_context == FollowUpContext(metric="2025 Aralık konut kredisi?", geography=("Adana",))
    assert agent.registry.user_text == "2025 Aralık konut kredisi?" and agent.registry.sanctioned_locators == {"https://www.bddk.org.tr/x"}
    assert again.get("/api/answers/0/table.csv").status_code == 200, "dışa aktarım tablosu da geri geldi"
    assert again.get("/api/status").json()["history"][0]["question"] == "2025 Aralık konut kredisi?"


def test_yeni_sohbet_ve_gecis_ajani_yeniden_kurmaz_ayni_calisma_alani(tmp_path) -> None:
    made: list[MemoryAgent] = []
    client = _app(tmp_path, made)
    agent = made[-1]
    ws = agent.workspace
    client.post("/api/ask", json={"question": "birinci soru"})
    first = client.get("/api/conversations").json()["active"]

    new = client.post("/api/conversations").json()["active"]
    assert new != first and client.get("/api/answers").json() == []
    assert agent.workspace is ws and not ws.has_table and agent._history == [], "araçlar aynı nesneyi tutar; içi boşalır"
    assert agent._follow_up_context == FollowUpContext(), "önceki sohbetin takip bağlamı yeni sohbete taşınmaz"
    assert client.post("/api/conversations").json()["active"] == new, "soru sorulmamış sohbette yeni sohbet yenisini açmaz"

    client.post("/api/ask", json={"question": "ikinci soru"})
    assert [i["title"] for i in client.get("/api/conversations").json()["items"]] == ["ikinci soru", "birinci soru"]
    assert client.post(f"/api/conversations/{first}/open").json()["active"] == first
    assert [i["title"] for i in client.get("/api/conversations").json()["items"]] == ["birinci soru", "ikinci soru"], "en son kullanılan en üstte"
    assert [a["question"] for a in client.get("/api/answers").json()] == ["birinci soru"]
    assert agent.workspace is ws and ws.has_table and agent._history[0].content == "birinci soru"
    assert agent._follow_up_context.metric == "birinci soru", "açılan sohbetin kendi takip bağlamı geri gelir"
    client.post("/api/ask", json={"question": "birinci sohbette devam"})
    assert [a["index"] for a in client.get("/api/answers").json()] == [0, 1]
    assert len(made) == 1, "sohbet geçişi ajanı yeniden kurmaz"
    assert client.post("/api/conversations/zzzzzzzzzzzz/open").status_code == 404
    assert client.delete("/api/conversations/../../etc").status_code in (404, 405)


def test_silme_sifirlama_ve_sorusuz_gecis_yuklemeleri_siler(tmp_path) -> None:
    made: list[MemoryAgent] = []
    client = _app(tmp_path, made)
    store = ConversationStore(tmp_path / "conversations")
    up = client.post("/api/upload", files={"file": CSV}).json()
    client.post("/api/ask", json={"question": f"Bu dosyayı analiz et.\n\nDosya: {up['path']}"})
    cid = client.get("/api/conversations").json()["active"]
    assert client.get("/api/conversations").json()["items"][0]["title"] == "Bu dosyayı analiz et."

    client.post("/api/conversations")
    assert Path(up["path"]).is_file(), "yeni sohbete geçmek eski sohbetin dosyasını silmez"
    orphan = client.post("/api/upload", files={"file": CSV}).json()
    client.post(f"/api/conversations/{cid}/open")
    assert not Path(orphan["path"]).exists(), "soru sorulmamış sohbetin yüklemesi geçişte silinir"
    assert client.get("/api/uploads").json()[0]["path"] == up["path"], "açılan sohbetin yüklemeleri geri gelir"

    other = client.post("/api/conversations").json()["active"]
    assert client.delete(f"/api/conversations/{cid}").json()["active"] == other
    assert not Path(up["path"]).exists() and not store.exists(cid)

    up2 = client.post("/api/upload", files={"file": CSV}).json()
    client.post("/api/ask", json={"question": "ikinci"})
    cid2 = client.get("/api/conversations").json()["active"]
    client.post("/api/reset")
    assert not Path(up2["path"]).exists() and not store.exists(cid2) and client.get("/api/conversations").json()["items"] == []


def test_tam_sifirlama_sohbetleri_korur_eski_diye_isaretler(tmp_path) -> None:
    assert all("conversations" not in str(p) for _, p in ResetPaths(data_root=tmp_path, db_path=tmp_path / "l.duckdb").candidates())
    made: list[MemoryAgent] = []
    client = _app(tmp_path, made)
    client.post("/api/ask", json={"question": "sıfırlamadan önceki soru"})
    old = client.get("/api/conversations").json()["active"]
    client.post("/api/conversations")
    ConversationStore(tmp_path / "conversations").bump_epoch()
    items = {i["id"]: i for i in client.get("/api/conversations").json()["items"]}
    assert items[old]["stale"] is True
    client.post(f"/api/conversations/{old}/open")
    assert client.get("/api/conversations").json()["active_stale"] is True


def test_bellek_kipinde_sohbet_listede_ama_kalici_degil(tmp_path) -> None:
    made: list[MemoryAgent] = []
    client = _app(tmp_path, made, store=False)
    client.post("/api/ask", json={"question": "bellekteki soru"})
    lst = client.get("/api/conversations").json()
    assert lst["persistent"] is False and [i["title"] for i in lst["items"]] == ["bellekteki soru"]
    assert client.post(f"/api/conversations/{lst['active']}/open").status_code == 404


def test_yeniden_acilista_en_son_bakilan_sohbet_acilir(tmp_path) -> None:
    client = _app(tmp_path, [])
    client.post("/api/ask", json={"question": "eski sohbet"})
    old = client.get("/api/conversations").json()["active"]
    client.post("/api/conversations")
    client.post("/api/ask", json={"question": "yeni sohbet"})
    client.post(f"/api/conversations/{old}/open")           # soru sormadan eski sohbete dönüldü; kayıt tarihi değişmedi
    again = _app(tmp_path, [])
    assert again.get("/api/conversations").json()["active"] == old
    assert [a["question"] for a in again.get("/api/answers").json()] == ["eski sohbet"]


def test_arayuzde_solda_sohbet_listesi_yeni_sohbet_ve_onayli_silme() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    left = html[html.index('<aside class="left">'):html.index("</aside>")]
    assert 'id="conv-list"' in left and 'id="btn-new2"' in left, "sohbet listesi sol panelde, sürekli görünür"
    assert "btn-menu" not in html and "drawer" not in html, "hamburger menü yok (kullanıcı, 16 Eyl)"
    assert 'id="session"' not in html and "Bu oturum" not in html, "oturum listesi menüye taşındı"
    assert "Bu sohbet ve yüklediği dosyalar silinsin mi?" in html and "Sohbeti sil ve sıfırla" in html
