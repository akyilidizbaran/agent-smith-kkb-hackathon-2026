"""AnalyticsAgent — motorun harness'ı.

Tasarım ilkesi (hackathon açılışında açıkça söylendi):
    "Harness yapısını daha güçlü yapın, LLM'e en az işi bırakın."

Bu yüzden model şunları YAPMAZ:
  - hesap yapmaz (DuckDB/pandas yapar),
  - ham veriyi görmez (şema + birkaç örnek satır görür),
  - kendi hatasını sessizce yutmaz (hata metni geri verilir, düzeltir).

Model sadece şunu yapar: hangi aracın, hangi argümanlarla çağrılacağına karar
verir ve sonucu yorumlar. Bu ayrım sayesinde 8B'lik bir model ile çalışan
sistem, demo gününde daha güçlü modelle daha da iyi çalışır.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..llm.base import ChatMessage, LLMClient, ToolCall
from .registry import ToolRegistry
from .tool import ToolResult
from .workspace import AnalysisWorkspace

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Sen Türkiye ekonomisi ve bankacılık verileri üzerinde çalışan bir veri analisti ajansın.

GÖREVİN: Kullanıcının doğal dildeki sorusunu anla, doğru veri kaynağını ve aracı seç, \
analizi adım adım yürüt ve sonucu kanıtıyla birlikte sun.

ZORUNLU İŞ SIRASI — bu sırayı atlama:
  1. lakehouse_search      → hangi tablo var?
  2. lakehouse_describe    → kolonlar, birimler, kapsam ne?
  3. lakehouse_distinct_values → filtreleyeceğin kalem/kategori adının GERÇEĞİ ne?
  4. lakehouse_query       → sorguyu çalıştır
Bir kalem adını, kolon adını veya kategori değerini ASLA tahminle yazma. \
3. adımı atlarsan sorgun büyük olasılıkla boş döner veya yanlış kalemleri toplar.

HESAPLAMA KURALI (en önemli kural):
Sen bir hesap makinesi DEĞİLSİN. Toplama, çıkarma, ortalama, yüzde değişim, büyüme oranı, \
fark — bunların HEPSİNİ SQL içinde yaptır. Araçtan dönen sayıları asla kendin işleme; \
olduğu gibi aktar. Bir değişim veya oran gerekiyorsa bunu hesaplayan YENİ bir sorgu yaz.
Örnek: aylık değişim için LAG kullan:
  SELECT donem, toplam, toplam - LAG(toplam) OVER (ORDER BY donem) AS aylik_degisim FROM ...

BİRİM KURALI:
Sorgu sonucunda birimler ayrıca bildirilir. Cevabında sayıyı YAZDIĞIN birimle birlikte ver \
("523.455 milyon TL" gibi). Birimi kendin çevirme, dönüştürme yapma.

DİĞER KURALLAR:
- ASLA veri uydurma. Bir sayıyı ancak bir araçtan aldıysan söyleyebilirsin. \
İstenen dönem tablonun kapsamı dışındaysa "bu veri kaynakta yok" de.
- Her cevapta sayıların kaynağını belirt (hangi kurum, hangi tablo, hangi dönem).
- Aktif bir analiz tablosu varsa ve kullanıcı "tabloyu bozmadan" / "bu tabloya" diyorsa, \
YENİ tablo kurma; mevcut tablo üzerinde sütun ekleme veya dönüştürme yap.
- Alt toplam satırlarını (is_alt_toplam = TRUE) alt kalemlerle birlikte toplama; mükerrer sayım olur.
- Kullanıcının sorusunu cevaplayan sorguyu her zaman as_active_table=true ile çalıştır; \
tek satırlık sonuçlar da analiz tablosudur.
- Bir kalem sorulduğunda TEK kalem seç. Benzer isimli kalemleri (takipteki, dövize endeksli, \
alt toplam) kullanıcı istemedikçe aynı sorguya katma; aynı döneme birden çok satır düşerse \
tablo bozulur.
- Kullanıcıya Türkçe, net ve kısa cevap ver. Ara adımları anlatma; sonucu ve gerekçesini anlat.

Bir araç hata döndürürse hatayı oku, çağrını düzelt ve tekrar dene. \
Yeterli bilgiye ulaştığında araç çağırmayı bırak ve nihai cevabını yaz."""

# Native tool-calling desteklemeyen modeller için yedek protokol.
JSON_PROTOCOL_PROMPT = """
ARAÇ KULLANIMI: Bir araç çağırmak istediğinde SADECE şu formatta JSON döndür, \
başka hiçbir metin yazma:
{"tool": "arac_adi", "args": {"parametre": "deger"}}

Nihai cevabını verirken JSON kullanma, doğrudan Türkçe metin yaz.

KULLANILABİLİR ARAÇLAR:
"""


@dataclass
class AgentStep:
    """Tek bir düşün-çağır-gözlemle adımının kaydı.

    Trace sadece hata ayıklama için değil: demoda 'bu sonuca nasıl vardın?'
    sorusuna karşı izlenebilirlik kanıtımız.
    """

    index: int
    thought: str = ""
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""
    ok: bool = True
    duration_ms: float = 0.0


@dataclass
class AgentAnswer:
    text: str
    steps: list[AgentStep] = field(default_factory=list)
    workspace: AnalysisWorkspace | None = None
    hit_step_limit: bool = False

    def trace_text(self) -> str:
        lines = []
        for s in self.steps:
            mark = "✓" if s.ok else "✗"
            if s.tool_name:
                lines.append(
                    f"{mark} [{s.index}] {s.tool_name}({json.dumps(s.tool_args, ensure_ascii=False)[:120]})"
                    f" → {s.result_summary[:160]} ({s.duration_ms:.0f}ms)"
                )
            elif s.thought:
                lines.append(f"  [{s.index}] düşünce: {s.thought[:160]}")
        return "\n".join(lines)


class AnalyticsAgent:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        *,
        workspace: AnalysisWorkspace | None = None,
        max_steps: int = 10,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.workspace = workspace or AnalysisWorkspace()
        self.max_steps = max_steps
        self._system_prompt = system_prompt
        self._history: list[ChatMessage] = []  # turlar arası konuşma hafızası

    def reset(self) -> None:
        self._history.clear()
        self.workspace = AnalysisWorkspace()

    # ------------------------------------------------------------------
    def ask(self, question: str) -> AgentAnswer:
        """Bir soruyu uçtan uca cevaplar."""
        messages = self._build_messages(question)
        steps: list[AgentStep] = []
        native = self.llm.supports_native_tools()
        tools = self.registry.schemas() if native else None

        for i in range(1, self.max_steps + 1):
            started = time.perf_counter()
            response = self.llm.chat(messages, tools=tools)

            calls = response.tool_calls if native else self._parse_json_call(response.content)

            # --- Araç çağrısı yoksa: nihai cevap ---
            if not calls:
                answer_text = self._strip_reasoning(response.content)
                steps.append(
                    AgentStep(
                        index=i,
                        thought="nihai cevap",
                        result_summary=answer_text[:200],
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                )
                self._history.append(ChatMessage(role="user", content=question))
                self._history.append(ChatMessage(role="assistant", content=answer_text))
                return AgentAnswer(text=answer_text, steps=steps, workspace=self.workspace)

            # --- Araçları çalıştır ---
            messages.append(
                ChatMessage(
                    role="assistant",
                    content=response.content if native else "",
                    tool_calls=calls if native else [],
                )
            )
            for call in calls:
                result = self.registry.execute(call.name, call.arguments)
                elapsed = (time.perf_counter() - started) * 1000
                steps.append(
                    AgentStep(
                        index=i,
                        tool_name=call.name,
                        tool_args=call.arguments,
                        result_summary=result.content[:300],
                        ok=result.ok,
                        duration_ms=elapsed,
                    )
                )
                log.info("adım %d: %s -> %s", i, call.name, "ok" if result.ok else "HATA")
                messages.append(self._result_message(call, result, native=native))

        # --- Adım limiti ---
        final = self.llm.chat(
            messages
            + [
                ChatMessage(
                    role="user",
                    content="Adım limitine ulaşıldı. Şu ana kadar TOPLADIĞIN VERİLERLE "
                    "elinden gelen en iyi cevabı ver ve neyi tamamlayamadığını belirt.",
                )
            ]
        )
        text = self._strip_reasoning(final.content)
        return AgentAnswer(text=text, steps=steps, workspace=self.workspace, hit_step_limit=True)

    # ------------------------------------------------------------------
    def _build_messages(self, question: str) -> list[ChatMessage]:
        system = self._system_prompt
        if not self.llm.supports_native_tools():
            system += "\n" + JSON_PROTOCOL_PROMPT + self.registry.describe()

        msgs = [ChatMessage(role="system", content=system)]
        msgs += self._history[-8:]  # son turlar — bağlamı korur, pencereyi şişirmez

        # Aktif tablo varsa modele durumu hatırlat: "tabloyu bozmadan" akışının anahtarı.
        if self.workspace.has_table:
            msgs.append(
                ChatMessage(
                    role="system",
                    content="MEVCUT ANALİZ DURUMU:\n" + self.workspace.describe_for_llm(),
                )
            )
        msgs.append(ChatMessage(role="user", content=question))
        return msgs

    def _result_message(self, call: ToolCall, result: ToolResult, *, native: bool) -> ChatMessage:
        """Araç sonucunu modele geri verir.

        Ham veri buraya KONMAZ; workspace'te tutulur, modele özeti gider.
        """
        if native:
            return ChatMessage(role="tool", content=result.content, tool_call_id=call.id)
        return ChatMessage(role="user", content=f"[{call.name} sonucu]\n{result.content}")

    @staticmethod
    def _parse_json_call(content: str) -> list[ToolCall]:
        """JSON-protokol modunda araç çağrısını ayıklar.

        Küçük modeller JSON'u markdown bloğu içine ya da açıklama metninin
        arasına gömer; ikisini de tolere ediyoruz.
        """
        if not content:
            return []
        blob = content.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", blob, re.S)
        if fenced:
            blob = fenced.group(1)
        else:
            brace = re.search(r"\{.*\}", blob, re.S)
            if not brace:
                return []
            blob = brace.group(0)
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, dict) or "tool" not in parsed:
            return []
        return [
            ToolCall(
                id=f"call_{int(time.time() * 1000)}",
                name=str(parsed["tool"]),
                arguments=parsed.get("args") or {},
            )
        ]

    @staticmethod
    def _strip_reasoning(text: str) -> str:
        """Reasoning modellerinin <think> bloklarını kullanıcıdan gizler.

        Qwen3 ve DeepSeek sınıfı modeller düşünce zincirini bu etiketle
        döndürüyor; nihai cevapta görünmemeli.
        """
        cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
        return cleaned.strip()
