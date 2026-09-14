"""`clarify` — sonucu değiştiren belirsizlikte TEK netleştirme sorusu; turu bitirir (V3 §3.9; Büşra, 16 Eyl).

Neden var (ölçüldü, 14–15 Eyl UEB): uygunluk kapısı (core/fitness) "kısmen" dediğinde — dosyada istenen ölçümün
adıyla kolon yok ('deger' kolonu), tablo bir alt kümeye kısıtlı — model bazen uyarıyı yazıp yine de sayı üretiyor,
bazen kendi seçtiği kolonu doğru sayıyor. Sistem promptundaki NETLEŞTİRME KURALI serbest metne dayanır; M16
ölçümünde (14 Eyl) aynı bilgi modele not olarak verildiğinde de model sormadan birini seçti (L10, iki koşu).
Bu araç soruyu DETERMİNİSTİK kapıya bağlar: yalnız kapı "kısmen" demişse VE belirsizlik ölçümü ya da alt kümeyi
ilgilendiriyorsa (sayıyı değiştirir) çağrılabilir; tur başına en çok bir kez; çağrı turu bitirir — model yeniden
çağrılmaz, sayı üretilmez, soru kullanıcıya gider (agent kancası). Kullanıcı cevap verince harness bekleyen soru
mekanizmasıyla (pending_question) devam eder.

Sunum tercihleri (sıralama, yuvarlama, grafik türü) için sorulmaz: kapı izin vermez, model kendisi seçer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.errors import ToolError
from ..core.tool import Tool, ToolResult

CLARIFY_PROMPT_RULES = """

NETLEŞTİRME ARACI: Yüklenen tablonun kartı 'uygunluk: kısmen' diyor ve belirsizlik SAYIYI değiştiriyorsa (hangi kolon \
istenen ölçüm, tablo hangi alt kümeye ait) tahmin edip sayı üretme: clarify aracını çağır (tek soru, 2–4 somut seçenek). \
Araç turu bitirir; kullanıcı cevap verince devam edersin. Sunum tercihleri için sorma. Tur başına en çok bir kez."""

#: Kapının izin verdiği belirsizlik boyutları: ölçüm (hangi kolon) ve varlık/alt küme. Dönem/granülarite ret üretir,
#: kalite uyarıları cevapta söylenir; ikisi de soru değildir.
IMPACT_DIMS = ("measure", "entity")


class ClarifyParams(BaseModel):
    question: str = Field(min_length=5, description="Kullanıcıya sorulacak TEK soru, Türkçe, soru işaretiyle biter")
    options: list[str] = Field(min_length=2, max_length=4, description="2–4 somut seçenek (kolon adı / alt küme / seri adı)")
    why: str = Field(description="Bu bilgi olmadan hangi sayının değişeceği, tek cümle Türkçe")


class ClarifyTool(Tool):
    name = "clarify"
    role = "narrate"
    description = (
        "Sonucu değiştiren bir belirsizlikte (yüklü tablonun hangi kolonu istenen ölçüm, tablo hangi alt kümeye ait) "
        "kullanıcıya TEK netleştirme sorusu sorar ve turu bitirir; sayı üretilmez. Yalnız tablo kartı 'uygunluk: kısmen' "
        "dediğinde çalışır; tur başına bir kez. Sunum tercihleri için kullanma."
    )
    Params = ClarifyParams

    def __init__(self, registry: object | None = None) -> None:
        self._registry = registry
        self._asked_turn: int | None = None

    def _turn(self) -> int:
        return int(getattr(self._registry, "turn", 0) or 0)

    def check_policy(self, params: ClarifyParams) -> ToolError | None:
        turn = self._turn()
        if self._asked_turn == turn:
            return ToolError(error_code="CLARIFY_NOT_ALLOWED", layer="policy", retryable=False, terminal=False,
                             message="Bu turda zaten bir netleştirme soruldu; ikinci soru sorulmaz.",
                             hint="Eldeki veriyle cevap ver; kalan belirsizliği cevabın ilk cümlesinde söyle.")
        fit = getattr(self._registry, "last_fitness", None) or {}
        same_turn = fit.get("turn") == turn
        dims = fit.get("dims") or {}
        impact = fit.get("decision") == "partial" and any(dims.get(d) == "partial" for d in IMPACT_DIMS)
        if not (same_turn and impact):
            return ToolError(error_code="CLARIFY_NOT_ALLOWED", layer="policy", retryable=False, terminal=False,
                             message=("Netleştirme yalnız uygunluk kapısı bu turda 'kısmen' dediğinde ve belirsizlik ölçümü ya da "
                                      "alt kümeyi ilgilendirdiğinde sorulur; şu an böyle bir durum yok."),
                             hint="Eldeki veriyle cevap ver; kart UYARI taşıyorsa cevabın ilk cümlesi o uyarıdır.")
        return None

    def run(self, params: ClarifyParams) -> ToolResult:
        self._asked_turn = self._turn()
        q = params.question.strip()
        if not q.endswith("?"):
            q += "?"
        options = [o.strip() for o in params.options if o and o.strip()]
        text = "\n".join([params.why.strip(), "", "Seçenekler:", *[f"- {o}" for o in options], "", q])
        return ToolResult(content=text, artifacts={"clarify": {"question": q, "options": options, "why": params.why.strip()}})


__all__ = ["CLARIFY_PROMPT_RULES", "IMPACT_DIMS", "ClarifyParams", "ClarifyTool"]
