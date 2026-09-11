"""V3 harness — Batched ReAct + sınır doğrulama (docs/ARCHITECTURE_V3.md §3.1).

Ekip döngüsünün omurgası korunur (model araç seçer, hesap DuckDB'de, hata
modele döner). Eklenenler, her biri Blok C'de ölçülmüş [EMP]:

  - katalog ön-yükleme (LLM turu 6,9 → 3,9)
  - tur içi paralel araç yürütme + "bağımsız çağrıları aynı turda ver" talimatı
    (yalnız ön-yüklemeyle birlikte faydalı: tek başına 6/7)
  - kısa cevap (2,9 tur / 3,3 s, 7/7)
  - grounding guard (shadow | enforce): cevaptaki sayılar araç çıktısında yoksa
    bir kez yeniden üretim
  - reasoning yükseltme: 2. ardışık araç hatasında `low`
  - yapılandırılmış hata: retryable=False → araçsız cevap turu (güvenli
    başarısızlık), araç başına ≤2 onarım, soru başına ≤N tur
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.domain import DomainProfile
from kkb_agent.llm.base import ChatMessage, LLMClient, ToolCall

from ..errors import ToolError
from .grounding import causal_language, grounding_check
from .tool import ToolResult
from .validator import ToolRegistry

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Sen {domain} üzerinde çalışan bir veri analisti ajansın.

GÖREVİN: Kullanıcının sorusunu anla, doğru tabloyu ve aracı seç, analizi yürüt, sonucu kanıtıyla sun.

ÖN-YÜKLÜ KATALOG: Tablolar, kolonlar, birimler, kapsam ve kırılım kolonlarının GERÇEK değerleri \
aşağıda verildi. Keşif aracı çağırmadan DOĞRUDAN lakehouse_query ile başla. Kalem/kategori adını \
yalnızca listeden BİREBİR kopyala; listede olmayan bir ad yazma. Yalnızca listede bulamadığın bir şey \
için lakehouse_search / lakehouse_describe / lakehouse_distinct_values kullan.

ARAÇ ÇAĞRISI KURALI: Birbirine bağımlı olmayan çağrıları AYNI turda, ayrı tool_call'lar olarak ver \
(ör. iki farklı kalem için iki sorgu). Birinin sonucunu beklemeden hepsini birden iste.

HESAPLAMA KURALI (en önemli kural): Sen bir hesap makinesi DEĞİLSİN. Toplama, fark, ortalama, yüzde \
değişim — hepsini SQL'de ya da workspace_compute_column ile yaptır. Araçtan dönen sayıları olduğu gibi \
aktar; cevabında araç çıktısında olmayan hiçbir sayı bulunmasın.

BİRİM KURALI: Sayıyı araç çıktısındaki birim etiketiyle yaz ("523.455 milyon TL"). Birim çevirme.

DİĞER KURALLAR:
- ASLA veri uydurma. Bir hata "tekrar denemeyle çözülmez" diyorsa kullanıcıya durumu açıkla; \
istenen dönem kapsam dışıysa eldeki aralığı söyle.
- Alt toplam satırlarını (is_alt_toplam = TRUE) alt kalemlerle birlikte toplama.
- Kullanıcının sorusunu cevaplayan sorguyu as_active_table=true ile çalıştır.
- Bir kalem sorulduğunda TEK kalem seç; benzer isimli kalemleri istenmedikçe aynı sorguya katma.
- Aktif tablo varken kullanıcı "tabloyu bozmadan", "yeni sütun olarak" diyorsa lakehouse_query \
KULLANMA: başka veriyi sütun olarak eklemek için workspace_add_column, mevcut sütunlardan hesap için \
workspace_compute_column.
- lakehouse_query ve workspace araçlarının sonucu zaten özetlenir; workspace_show'u yalnızca kullanıcı \
tabloyu görmek istediğinde çağır, doğrulama için çağırma.
- Muhatabın bir {audience}, geliştirici DEĞİL: cevapta SQL, kolon adı, araç adı, hata mesajı YAZMA.
- Nedensellik iddiası kurma: "birlikte hareket etti", "öncülük etti" de; "neden oldu" deme.

CEVAP UZUNLUĞU: Nihai cevap en fazla {max_words} kelime, Türkçe. Tablo kullanıcıya zaten \
gösteriliyor; satırları tek tek yazma. Sonuç, kaynak (kurum, tablo, dönem) ve varsa uyarı.

Bir araç hata döndürürse hatayı oku, adayları/ipucunu kullanarak çağrını düzelt ve tekrar dene. \
Yeterli bilgiye ulaştığında araç çağırmayı bırak ve nihai cevabını yaz."""

_XML_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


@dataclass(frozen=True)
class AgentConfig:
    max_turns: int = 8               # soru başına LLM turu
    max_repairs_per_tool: int = 2    # aynı araç için ardışık hata sayısı
    parallel: bool = True
    grounding: str = "enforce"       # "off" | "shadow" | "enforce"
    escalate: bool = True
    answer_max_words: int = 120
    nudge_if_no_data: bool = True
    # Üretim tavanı. 11 Eylül seed benchmark'ında (G5) model cevap turunda saçmalayıp 103 s
    # boyunca token üretti; tavan olmadan en kötü durum sınırsız. Araç turları kısa JSON,
    # 700 token en uzun SQL'e de yeter.
    max_tokens: int = 700


@dataclass
class AgentStep:
    index: int
    thought: str = ""
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""
    ok: bool = True
    duration_ms: float = 0.0
    error_code: str | None = None
    layer: str | None = None


@dataclass
class AgentAnswer:
    text: str
    steps: list[AgentStep] = field(default_factory=list)
    workspace: AnalysisWorkspace | None = None
    hit_step_limit: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def trace_text(self) -> str:
        lines = []
        for s in self.steps:
            mark = "✓" if s.ok else "✗"
            if s.tool_name:
                code = f" [{s.error_code}]" if s.error_code else ""
                lines.append(
                    f"{mark} [{s.index}] {s.tool_name}({json.dumps(s.tool_args, ensure_ascii=False)[:120]})"
                    f"{code} → {s.result_summary[:160]} ({s.duration_ms:.0f}ms)"
                )
            elif s.thought:
                lines.append(f"  [{s.index}] {s.thought[:160]}")
        return "\n".join(lines)


class V3Agent:
    DATA_PRODUCING_TOOLS = frozenset({"lakehouse_query", "workspace_add_column", "workspace_compute_column", "workspace_show"})

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        *,
        workspace: AnalysisWorkspace | None = None,
        profile: DomainProfile | None = None,
        config: AgentConfig | None = None,
        catalog_context: str = "",
        domain_context: str = "",
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.workspace = workspace or AnalysisWorkspace()
        self.profile = profile or registry.profile
        self.config = config or AgentConfig()
        self.catalog_context = catalog_context
        self.domain_context = domain_context
        self._system_prompt = self.profile.render(system_prompt.replace("{max_words}", str(self.config.answer_max_words)))
        self._history: list[ChatMessage] = []

    def reset(self) -> None:
        self._history.clear()
        self.workspace = AnalysisWorkspace()

    # ------------------------------------------------------------------
    def ask(self, question: str) -> AgentAnswer:
        cfg = self.config
        self.registry.active_question = question
        messages = self._build_messages(question)
        steps: list[AgentStep] = []
        tools = self.registry.schemas()
        produced_data = False
        nudged = False
        regenerated = False
        force_final = False
        llm_turns = 0
        tokens = 0
        consecutive_errors = 0
        repairs: dict[str, int] = {}
        error_codes: list[str] = []
        tool_texts: list[str] = []
        grounding = ""
        seen_ok: dict[tuple[str, str], int] = {}   # (araç, argüman json) → başarıyla çalıştığı tur
        duplicates = 0

        for turn in range(1, cfg.max_turns + 1):
            started = time.perf_counter()
            extra = {"reasoning_effort": "low"} if (cfg.escalate and consecutive_errors >= 2) else None
            response = self._chat(messages, tools=None if force_final else tools, extra=extra)
            llm_turns += 1
            tokens += sum(response.usage.values()) if response.usage else 0
            calls = response.tool_calls or self._parse_xml_calls(response.content)

            if not calls or force_final:
                candidate = self._strip_reasoning(response.content)
                if cfg.grounding != "off" and produced_data:
                    grounding = grounding_check(question, candidate, tool_texts)
                    causal = causal_language(candidate)
                    if causal:
                        grounding += f" | CAUSAL:{','.join(causal)}"
                    if cfg.grounding == "enforce" and not regenerated and (grounding.startswith("MISS") or causal):
                        regenerated = True
                        steps.append(AgentStep(index=turn, thought=f"grounding: {grounding}", ok=False,
                                               duration_ms=(time.perf_counter() - started) * 1000))
                        messages.append(ChatMessage(role="assistant", content=response.content))
                        problems = []
                        if grounding.startswith("MISS"):
                            problems.append(f"şu sayılar hiçbir araç çıktısında yok: {grounding.split('|')[0][5:].strip()}")
                        if causal:
                            problems.append(f"nedensellik ifadesi var: {', '.join(causal)}")
                        messages.append(ChatMessage(
                            role="user",
                            content="Cevabında " + "; ".join(problems) + ". Yalnızca araçlardan dönen sayıları "
                            "kullan, hesap gerekiyorsa workspace_compute_column ile yaptır; nedensellik iddiası "
                            "kurma. Cevabını yeniden yaz.",
                        ))
                        force_final = False
                        continue
                    if cfg.grounding == "enforce" and regenerated and grounding.startswith("MISS"):
                        # V3 §3.1 adım 4: ikinci başarısızlıkta cevap gider ama doğrulanamayan
                        # sayılar açıkça işaretlenir; tablo zaten kullanıcıda.
                        unverified = grounding.split("|")[0][5:].strip()
                        candidate += f"\n\n(Not: anlatımdaki şu değerler araç çıktısında birebir doğrulanamadı: {unverified}. Kesin değerler için tabloya bakın.)"
                if not produced_data and not nudged and not force_final and cfg.nudge_if_no_data:
                    nudged = True
                    steps.append(AgentStep(index=turn, thought="veri çekilmeden cevap denendi — geri gönderildi",
                                           ok=False, duration_ms=(time.perf_counter() - started) * 1000))
                    messages.append(ChatMessage(role="assistant", content=response.content))
                    messages.append(ChatMessage(
                        role="user",
                        content="Henüz hiçbir veri sorgusu çalıştırmadın. Katalog bilgisi cevap DEĞİLDİR. "
                        "Kullanıcının sorusunu cevaplayan sayıları lakehouse_query ile çek, sonra cevabını yaz.",
                    ))
                    continue
                steps.append(AgentStep(index=turn, thought="nihai cevap", result_summary=candidate[:200],
                                       duration_ms=(time.perf_counter() - started) * 1000))
                self._history.append(ChatMessage(role="user", content=question))
                self._history.append(ChatMessage(role="assistant", content=candidate))
                return AgentAnswer(text=candidate, steps=steps, workspace=self.workspace,
                                   extra=self._extra(llm_turns, tokens, grounding, error_codes))

            # --- araçları çalıştır (tur = paralel çağrı katmanı) ---
            messages.append(ChatMessage(role="assistant", content=response.content, tool_calls=calls))
            # Döngü kilidi (L4-01, 10 Eylül 2. oturum): model aynı sorguyu 7 kez tekrarlayıp tur
            # limitini yaktı. Aynı araç + aynı argüman zaten başarıyla çalıştıysa yeniden
            # çalıştırılmaz; ikinci tekrarda araçsız cevap turuna geçilir.
            fresh: list[ToolCall] = []
            dup_results: dict[str, ToolResult] = {}
            for c in calls:
                key = (c.name, json.dumps(c.arguments, sort_keys=True, ensure_ascii=False))
                if key in seen_ok:
                    duplicates += 1
                    dup_results[c.id] = ToolResult.fail(ToolError(
                        error_code="DUPLICATE_CALL", layer="policy",
                        message=f"'{c.name}' aynı argümanlarla zaten çalıştı (tur {seen_ok[key]}); sonucu yukarıda, yeniden çalıştırmak yeni bilgi vermez.",
                        hint="Elindeki sonuçla nihai cevabını yaz. Farklı bir bilgi gerekiyorsa argümanları değiştir.",
                    ))
                    if duplicates >= 2:
                        force_final = True
                else:
                    fresh.append(c)
            executed = dict(zip((c.id for c in fresh), self._execute_calls(fresh))) if fresh else {}
            results = [dup_results.get(c.id) or executed[c.id] for c in calls]
            for call, result in zip(calls, results):
                if result.ok:
                    seen_ok[(call.name, json.dumps(call.arguments, sort_keys=True, ensure_ascii=False))] = turn
                steps.append(AgentStep(
                    index=turn, tool_name=call.name, tool_args=call.arguments,
                    result_summary=result.content[:300], ok=result.ok,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    error_code=result.error_code, layer=result.error.layer if result.error else None,
                ))
                tool_texts.append(result.content)
                if result.data is not None and not result.data.empty:
                    tool_texts.append(result.data.to_string(index=False))
                if result.ok:
                    consecutive_errors = 0
                    repairs.pop(call.name, None)
                    if call.name in self.DATA_PRODUCING_TOOLS:
                        produced_data = True
                else:
                    consecutive_errors += 1
                    error_codes.append(result.error_code or "?")
                    repairs[call.name] = repairs.get(call.name, 0) + 1
                    if result.error is not None and not result.error.is_retryable:
                        force_final = True   # güvenli başarısızlık: bir sonraki tur araçsız
                    elif repairs[call.name] > cfg.max_repairs_per_tool:
                        force_final = True
                        tool_texts.append("")
                        messages.append(ChatMessage(
                            role="user",
                            content=f"'{call.name}' aracı {repairs[call.name]} kez hata verdi. Daha fazla deneme; "
                            "eldeki bilgiyle cevap ver ve neyi doğrulayamadığını söyle.",
                        ))
                log.info("tur %d: %s -> %s", turn, call.name, result.error_code or "ok")
                messages.append(ChatMessage(role="tool", content=result.content, tool_call_id=call.id))

        # --- tur limiti ---
        final = self._chat(messages + [ChatMessage(
            role="user",
            content="Tur limitine ulaşıldı. Şu ana kadar TOPLADIĞIN VERİLERLE en iyi cevabı ver ve neyi "
            "tamamlayamadığını belirt.",
        )], tools=None)
        text = self._strip_reasoning(final.content)
        return AgentAnswer(text=text, steps=steps, workspace=self.workspace, hit_step_limit=True,
                           extra=self._extra(llm_turns + 1, tokens, grounding, error_codes))

    # ------------------------------------------------------------------
    def _chat(self, messages, *, tools, extra=None):
        kwargs: dict[str, Any] = {"tools": tools, "max_tokens": self.config.max_tokens}
        if extra:
            kwargs["extra"] = extra
        try:
            return self.llm.chat(messages, **kwargs)
        except TypeError:
            # Ekip istemcisi `extra` almıyor; yükseltmesiz devam.
            return self.llm.chat(messages, tools=tools, max_tokens=self.config.max_tokens)

    def _execute_calls(self, calls: list[ToolCall]) -> list[ToolResult]:
        """Tablo değiştirmeyen çağrılar eşzamanlı, değiştirenler sırayla; sonuç sırası korunur."""
        if not self.config.parallel or len(calls) <= 1:
            return [self.registry.execute(c.name, c.arguments) for c in calls]
        results: list[ToolResult | None] = [None] * len(calls)

        def mutates(c: ToolCall) -> bool:
            t = self.registry.get(c.name)
            return bool(t is None or getattr(t, "mutates", False))

        ro = [(k, c) for k, c in enumerate(calls) if not mutates(c)]
        if ro:
            with cf.ThreadPoolExecutor(max_workers=min(4, len(ro))) as ex:
                futs = {ex.submit(self.registry.execute, c.name, c.arguments): k for k, c in ro}
                for fut, k in futs.items():
                    results[k] = fut.result()
        for k, c in enumerate(calls):
            if mutates(c):
                results[k] = self.registry.execute(c.name, c.arguments)
        return [r for r in results if r is not None]

    def _build_messages(self, question: str) -> list[ChatMessage]:
        system = self._system_prompt
        if self.catalog_context:
            system += "\n\nÖN-YÜKLÜ KATALOG:\n" + self.catalog_context
        if self.domain_context:
            system += "\n\n" + self.domain_context
        if self.workspace.has_table:
            system += "\n\nMEVCUT ANALİZ DURUMU:\n" + self.workspace.describe_for_llm()
        msgs = [ChatMessage(role="system", content=system)]
        msgs += self._history[-8:]
        msgs.append(ChatMessage(role="user", content=question))
        return msgs

    @staticmethod
    def _extra(llm_turns: int, tokens: int, grounding: str, error_codes: list[str]) -> dict[str, Any]:
        return {"llm_turns": llm_turns, "tokens": tokens, "grounding": grounding, "error_codes": error_codes}

    @staticmethod
    def _parse_xml_calls(content: str) -> list[ToolCall]:
        """Edge-case 11: `tool_calls` boş ama content'te <tool_call> XML'i var."""
        out: list[ToolCall] = []
        for i, m in enumerate(_XML_CALL.finditer(content or "")):
            try:
                obj = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
            name = obj.get("name") or obj.get("tool")
            if name:
                out.append(ToolCall(id=f"xml_{int(time.time() * 1000)}_{i}", name=str(name),
                                    arguments=obj.get("arguments") or obj.get("args") or {}))
        return out

    @staticmethod
    def _strip_reasoning(text: str) -> str:
        return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
