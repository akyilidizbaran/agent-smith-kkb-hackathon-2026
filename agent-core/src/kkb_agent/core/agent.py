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

from ..domain import DomainProfile
from ..llm.base import ChatMessage, LLMClient, ToolCall
from .errors import ToolError
from .registry import ToolRegistry
from .tool import ToolResult
from .workspace import AnalysisWorkspace

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Sen {domain} üzerinde çalışan bir veri analisti ajansın.

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
  SELECT {example_time_column}, {example_measure}, {example_measure} - \
LAG({example_measure}) OVER (ORDER BY {example_time_column}) AS degisim FROM ...

BİRİM KURALI:
Sorgu sonucunda birimler ayrıca bildirilir. Cevabında sayıyı YAZDIĞIN birimle birlikte ver \
("523.455 milyon TL" gibi). Birimi kendin çevirme, dönüştürme yapma.

DİĞER KURALLAR:
- ASLA veri uydurma. Bir sayıyı ancak bir araçtan aldıysan söyleyebilirsin. \
İstenen dönem tablonun kapsamı dışındaysa "bu veri kaynakta yok" de.
- Her cevapta sayıların kaynağını belirt (hangi kurum, hangi tablo, hangi dönem).
MEVCUT TABLO ÜZERİNDE ÇALIŞMA:
Aktif bir analiz tablosu varsa ve kullanıcı "tabloyu bozmadan", "bu tabloya", "yeni sütun \
olarak ekle", "buna ... da ekle" diyorsa lakehouse_query KULLANMA — yeni tablo kurarsan \
kullanıcının baktığı tablo kaybolur. Bunun yerine:
  - Başka bir veriyi sütun olarak eklemek için: workspace_add_column
  - Mevcut sütunlardan hesap türetmek için (yüzde değişim, oran, normalleştirme): \
workspace_compute_column
  - Tablonun son halini görmek için: workspace_show
- Alt toplam satırlarını (is_alt_toplam = TRUE) alt kalemlerle birlikte toplama; mükerrer sayım olur.
- Kullanıcının sorusunu cevaplayan sorguyu her zaman as_active_table=true ile çalıştır; \
tek satırlık sonuçlar da analiz tablosudur.
- Bir kalem sorulduğunda TEK kalem seç. Benzer isimli kalemleri (takipteki, dövize endeksli, \
alt toplam) kullanıcı istemedikçe aynı sorguya katma; aynı döneme birden çok satır düşerse \
tablo bozulur.
- Kullanıcıya Türkçe, net ve kısa cevap ver. Ara adımları anlatma; sonucu ve gerekçesini anlat.
- Muhatabın bir {audience}, geliştirici DEĞİL. Nihai cevapta SQL, kolon adı, araç adı, \
hata mesajı veya "sorgunuzu kontrol edin" türü teknik yönlendirme YAZMA. Veri yoksa bunu \
sade bir cümleyle söyle ve elde hangi dönemin bulunduğunu belirt.

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
    error_code: str | None = None   # ToolError.error_code; ölçüm ve trace için


@dataclass
class AgentAnswer:
    text: str
    steps: list[AgentStep] = field(default_factory=list)
    workspace: AnalysisWorkspace | None = None
    hit_step_limit: bool = False

    def error_codes(self) -> dict[str, int]:
        """Hangi hata sınıfı kaç kez oluştu.

        Serbest metin hatalarla bu sayılamıyordu; ölçek arttıkça hangi sınıfın
        bozulduğunu görmek gerekiyor (ADR-0025).
        """
        counts: dict[str, int] = {}
        for s in self.steps:
            if s.error_code:
                counts[s.error_code] = counts.get(s.error_code, 0) + 1
        return counts

    def trace_text(self) -> str:
        lines = []
        for s in self.steps:
            mark = "✓" if s.ok else "✗"
            if s.tool_name:
                code = f" {s.error_code}" if s.error_code else ""
                lines.append(
                    f"{mark}{code} [{s.index}] {s.tool_name}"
                    f"({json.dumps(s.tool_args, ensure_ascii=False)[:110]})"
                    f" → {s.result_summary[:150]} ({s.duration_ms:.0f}ms)"
                )
            elif s.thought:
                lines.append(f"  [{s.index}] düşünce: {s.thought[:160]}")
        return "\n".join(lines)


class AnalyticsAgent:
    # Yalnız bu araçlar "kullanıcının sorusunu cevaplayan veri" üretir.
    # Katalog araçları (search/describe/distinct_values) da DataFrame döndürür
    # ama bunlar keşif adımıdır; cevabın dayanağı olamaz.
    DATA_PRODUCING_TOOLS = frozenset(
        {
            "lakehouse_query",
            "workspace_add_column",
            "workspace_compute_column",
            "workspace_show",
        }
    )

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        *,
        workspace: AnalysisWorkspace | None = None,
        max_steps: int = 10,
        system_prompt: str = SYSTEM_PROMPT,
        profile: DomainProfile | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.workspace = workspace or AnalysisWorkspace()
        self.max_steps = max_steps
        # Alan bilgisi prompt'a koddan değil profilden girer (ADR-0012).
        # Profil verilmezse registry'ninki, o da yoksa nötr varsayılan kullanılır.
        self.profile = profile or registry.profile
        self._system_prompt = self.profile.render(system_prompt)
        self._history: list[ChatMessage] = []  # turlar arası konuşma hafızası

    def reset(self) -> None:
        self._history.clear()
        self.workspace = AnalysisWorkspace()

    # ------------------------------------------------------------------
    def ask(self, question: str) -> AgentAnswer:
        """Bir soruyu uçtan uca cevaplar."""
        self.registry.active_question = question
        messages = self._build_messages(question)
        steps: list[AgentStep] = []
        native = self.llm.supports_native_tools()
        tools = self.registry.schemas() if native else None
        produced_data = False   # veri getiren bir araç başarıyla çalıştı mı?
        nudged = False          # "önce veriyi çek" uyarısı bir kez verilir
        seen: set[tuple[str, str]] = set()   # (araç, argüman) — döngü kilidi
        terminal: ToolError | None = None    # tekrar denemeyle çözülmeyen hata

        for i in range(1, self.max_steps + 1):
            started = time.perf_counter()
            response = self.llm.chat(messages, tools=tools)

            calls = response.tool_calls if native else self._parse_json_call(response.content)

            # --- Araç çağrısı yoksa: nihai cevap ---
            if not calls:
                # Model bazen kataloğu okuyup veriyi hiç çekmeden cevap yazmaya
                # kalkıyor; ölçümde G5 her denemede 3 adımda burada duruyordu.
                # Cevabı reddetmiyoruz, bir kez geri gönderip veriyi çektiriyoruz.
                if not produced_data and not nudged:
                    nudged = True
                    steps.append(
                        AgentStep(
                            index=i,
                            thought="veri çekilmeden cevap denendi — geri gönderildi",
                            ok=False,
                            duration_ms=(time.perf_counter() - started) * 1000,
                        )
                    )
                    messages.append(ChatMessage(role="assistant", content=response.content))
                    messages.append(
                        ChatMessage(
                            role="user",
                            content="Henüz hiçbir veri sorgusu çalıştırmadın; yalnızca "
                            "katalogu inceledin. Katalog bilgisi cevap DEĞİLDİR. "
                            "Kullanıcının sorusunu cevaplayan sayıları lakehouse_query ile "
                            "çek, sonra cevabını yaz.",
                        )
                    )
                    continue

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
                # Döngü kilidi: model aynı çağrıyı tekrarlıyorsa sonuç değişmez.
                # Ölçülmüş hata modu: aynı sorgunun art arda 7 kez çalıştırılması.
                signature = (call.name, json.dumps(call.arguments, sort_keys=True, default=str))
                if signature in seen:
                    result = ToolResult.fail(
                        "DUPLICATE_CALL",
                        f"'{call.name}' aynı argümanlarla zaten çalıştırıldı; sonuç aynı olacak.",
                        hint="Argümanları değiştir ya da elindeki sonuçla cevaba geç.",
                        layer="harness",
                    )
                else:
                    seen.add(signature)
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
                        error_code=result.error.error_code if result.error else None,
                    )
                )
                if result.ok and call.name in self.DATA_PRODUCING_TOOLS:
                    produced_data = True
                if result.error is not None and not result.error.is_retryable:
                    terminal = result.error
                log.info("adım %d: %s -> %s", i, call.name, "ok" if result.ok else "HATA")
                messages.append(self._result_message(call, result, native=native))

            if terminal is not None:
                # Tekrar denemeyle çözülmeyecek bir hata: modele araç verilmeden
                # son bir tur. Aksi halde model aynı yolu farklı yazımlarla
                # denemeye devam ediyor ve adım limitini yakıyor (ADR-0017).
                final = self.llm.chat(
                    messages
                    + [
                        ChatMessage(
                            role="user",
                            content="Bu yoldan sonuç çıkmayacağı anlaşıldı. ARAÇ ÇAĞIRMA; "
                            "kullanıcıya durumu tek paragrafta açıkla: neyi isteyemediğini "
                            "ve elinde ne olduğunu söyle. Sayı uydurma.",
                        )
                    ]
                )
                text = self._strip_reasoning(final.content)
                self._history.append(ChatMessage(role="user", content=question))
                self._history.append(ChatMessage(role="assistant", content=text))
                return AgentAnswer(text=text, steps=steps, workspace=self.workspace)

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

        # Aktif tablo varsa modele durumu hatırlat: "tabloyu bozmadan" akışının anahtarı.
        # TEK system mesajı, en başta: MIA/vLLM ikinci bir system mesajını reddediyor
        # ("System message must be at the beginning"); Ollama tolere ediyordu.
        if self.workspace.has_table:
            system += "\n\nMEVCUT ANALİZ DURUMU:\n" + self.workspace.describe_for_llm()

        msgs = [ChatMessage(role="system", content=system)]
        msgs += self._history[-8:]  # son turlar — bağlamı korur, pencereyi şişirmez
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
