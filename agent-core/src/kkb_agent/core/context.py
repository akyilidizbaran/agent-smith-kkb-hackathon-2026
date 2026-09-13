"""Soruya göre sınırlı bağlam ön-yükleme — keşif turları LLM turu olmaktan çıkar (ADR-0013, D1).

Ölçülen adım profili: bir sorunun ilk 3–4 turu arama (search → describe →
distinct_values), hiçbiri karar değil. Büşra'nın V3 ölçümü (E8, Blok C): katalog
~6k token altındayken tamamı prompt'ta doğruluğu düşürmüyor ve turları 6,9 → 3,9'a
indiriyor; üstünde hem yavaşlıyor hem hata artıyor.

Bu modül kataloğun TAMAMINI değil, retriever'ın soruya göre seçtiği k seriyi bütçeyle
prompt'a koyar (yol haritası D1): 1.620 serilik gerçek katalogda "tamamı" 44 bin
token'dı. Seçilenler kompakt kart olarak, seçilmeyenler tek satırlık dizin olarak
(bütçe izin verirse) girer; model başka bir tabloya ihtiyaç duyarsa `lakehouse_search`
kayıtlı kalır (ADR-0013'ün riski: yanlış ön-yükleme modeli hapsetmemeli).

Değer keşfi kuralı (ADR-0009) bozulmaz: kırılım kolonlarının GERÇEK değerleri kartla
birlikte gelir; model onları görmüşse `distinct_values` turu yapılmış sayılır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..contracts.catalog import ColumnRole, DatasetSpec
from ..contracts.lakehouse import LakehouseClient

_TOKEN_CHARS = 3.2
"""Kabaca karakter/token; Qwen ailesinde Türkçe metin için ölçülen oran 3–3,5. Bütçe
kararı için yeterli; gerçek sayı LLM yanıtındaki usage ile ölçülür ve raporlanır."""


def estimate_tokens(text: str) -> int:
    return int(len(text) / _TOKEN_CHARS) + 1


@dataclass(frozen=True)
class CatalogContext:
    text: str
    mode: str                       # preloaded | index | empty | off
    tokens: int
    preloaded_ids: tuple[str, ...] = ()
    indexed: int = 0
    values_for: tuple[str, ...] = ()   # kırılım değerleri listelenen dataset'ler

    def summary(self) -> str:
        return (f"ön-yükleme[{self.mode}]: {len(self.preloaded_ids)} kart, {self.indexed} dizin satırı, "
                f"~{self.tokens} token" + (f", değerler: {', '.join(self.values_for)}" if self.values_for else ""))


def compact_card(spec: DatasetSpec, lakehouse: LakehouseClient) -> str:
    """Tam prompt kartının kısa hâli: kimlik, ad, kısa açıklama, ölçümler ve birim, kapsam,
    erişim SQL'i, uyarı notları. Kolon listesinin tamamı değil — gerektiğinde describe var."""
    measures = [c for c in spec.columns if c.role is ColumnRole.MEASURE]
    dims = [c for c in spec.columns if c.role is ColumnRole.DIMENSION]
    lines = [f"### {spec.dataset_id} — {spec.name}"]
    desc = " ".join(spec.description.split())
    lines.append(f"Açıklama: {desc[:220]}{'…' if len(desc) > 220 else ''}")
    lines.append(f"Frekans: {spec.frequency.value} | Dönem kolonu: {spec.time_column} | "
                 f"Kapsam: {spec.coverage.start} → {spec.coverage.end}")
    if measures:
        lines.append("Ölçümler: " + "; ".join(
            f"{c.name}" + (f" ({c.unit})" if c.unit else "") + (f" [{c.semantic_type.value}]" if c.semantic_type else "")
            for c in measures[:6]))
    if dims:
        lines.append("Kırılımlar: " + ", ".join(c.name for c in dims[:6]))
    if measures:
        try:
            sql = lakehouse.series_sql(spec.dataset_id, key_column=spec.time_column, value_column=measures[0].name)
            if not re.search(rf"\bFROM\s+{re.escape(spec.dataset_id)}\b", sql, re.I):
                lines.append(f"SQL erişimi ('{spec.dataset_id}' tablo adı DEĞİL): {sql}")
        except Exception:  # noqa: BLE001 — erişim kalıbı üretilemezse kart yine geçerli
            pass
    for n in spec.notes:
        if n.startswith("Fiziksel sorgu"):
            continue
        if any(k in n for k in ("DOĞRULANMAMIŞ", "TASLAK", "BAYAT", "GOLD TABLOSU", "bilinmiyor")):
            lines.append(f"UYARI: {n[:200]}")
    return "\n".join(lines)


def dimension_values(spec: DatasetSpec, lakehouse: LakehouseClient, *, max_values: int) -> list[str]:
    """Seed tarzı tablolarda kırılım kolonlarının gerçek değerleri (V3 E8): filtre uydurulmaz."""
    out: list[str] = []
    for col in spec.columns:
        if col.role is not ColumnRole.DIMENSION or col.dtype.upper() not in ("VARCHAR", "TEXT", "STRING"):
            continue
        if col.name in ("entity_id", "series_id"):
            continue  # seri-merkezli/Gold tablolarda tek değerli kimlik kolonları; liste gürültü olur
        has_flag = spec.column("is_alt_toplam") is not None
        select = f"{col.name}, is_alt_toplam" if has_flag else col.name
        try:
            res = lakehouse.execute_sql(
                f"SELECT DISTINCT {select} FROM {spec.dataset_id} ORDER BY 1 LIMIT {max_values + 1}"
            )
        except Exception:  # noqa: BLE001
            continue
        df = res.data
        if df.empty:
            continue
        lines = [f"'{col.name}' kolonundaki GERÇEK değerler ({min(len(df), max_values)} adet; filtrede birebir kullan, "
                 "SADECE BİRİNİ seç; benzer isimli kalemler farklı şeyleri ölçer):"]
        for row in df.head(max_values).itertuples(index=False):
            flag = "   ⚠ ALT TOPLAM (alt kalemlerle toplama)" if has_flag and bool(row[1]) else ""
            lines.append(f"  - {row[0]}{flag}")
        if len(df) > max_values:
            lines.append(f"  … (+{len(df) - max_values}; tam liste için lakehouse_distinct_values)")
        out.append("\n".join(lines))
    return out


def build_question_context(
    lakehouse: LakehouseClient,
    question: str,
    *,
    budget_tokens: int = 6000,
    k: int = 8,
    max_values: int = 60,
    values_if_at_most: int = 12,
    retrieval_mode: str = "auto",
    small_max: int = 60,
) -> CatalogContext:
    """Soruya göre seçilmiş kartlar + değerler, bütçe içinde; kalanlar dizin satırı.

    Kademe (ADR-0043): katalog `small_max`'ı aşmıyorsa (ya da mod `preload_all`) arama yok,
    hepsi kart olur ve bütçe neyi keserse o dizinde kalır; aksi hâlde adaptörün retriever'ı
    (BM25/hybrid + yüzler) ilk k'yı seçer."""
    if budget_tokens <= 0:
        return CatalogContext(text="", mode="off", tokens=0)
    specs = lakehouse.list_datasets()
    if not specs:
        return CatalogContext(text="", mode="empty", tokens=0)

    preload_all = retrieval_mode == "preload_all" or (retrieval_mode == "auto" and len(specs) <= small_max)
    if preload_all or len(specs) <= k:
        chosen = list(specs)
    else:
        chosen = list(lakehouse.search_datasets(question, limit=k))
    chosen_ids = [s.dataset_id for s in chosen]

    parts: list[str] = []
    used = 0
    preloaded: list[str] = []
    values_for: list[str] = []
    small_catalog = len(specs) <= values_if_at_most
    for spec in chosen:
        card = compact_card(spec, lakehouse)
        cost = estimate_tokens(card)
        if used + cost > budget_tokens:
            break
        parts.append(card)
        used += cost
        preloaded.append(spec.dataset_id)
        if small_catalog:
            for block in dimension_values(spec, lakehouse, max_values=max_values):
                bcost = estimate_tokens(block)
                if used + bcost > budget_tokens:
                    break
                parts.append(block)
                used += bcost
                if spec.dataset_id not in values_for:
                    values_for.append(spec.dataset_id)

    rest = [s for s in specs if s.dataset_id not in preloaded]
    indexed = 0
    if rest:
        index_lines = [f"- {s.dataset_id}: {s.name} [{s.frequency.value}, {s.coverage.start}→{s.coverage.end}]"
                       for s in rest]
        index = "DİĞER SERİLER (ayrıntı için lakehouse_search / lakehouse_describe):\n" + "\n".join(index_lines)
        icost = estimate_tokens(index)
        if used + icost <= budget_tokens:
            parts.append(index)
            used += icost
            indexed = len(rest)
        else:
            note = (f"Katalogda {len(rest)} seri daha var; ilgili olanı lakehouse_search ile bul.")
            parts.append(note)
            used += estimate_tokens(note)

    if not preloaded:
        return CatalogContext(text="\n\n".join(parts), mode="index", tokens=used, indexed=indexed)
    return CatalogContext(
        text="\n\n".join(parts), mode="preloaded", tokens=used,
        preloaded_ids=tuple(preloaded), indexed=indexed, values_for=tuple(values_for),
    )


PRELOAD_PROMPT_RULES = """

ÖN-YÜKLENEN KATALOG:
Aşağıda soruya göre seçilmiş serilerin kartları ve varsa kırılım kolonlarının GERÇEK değerleri var. \
Kartı gördüğün seri için lakehouse_search ve lakehouse_describe çağırma; değerler listelendiyse \
lakehouse_distinct_values de gerekmez — doğrudan sorguya (lakehouse_query / gold_*) geç. \
Yalnız kartlarda olmayan bir seri gerekiyorsa lakehouse_search kullan."""


__all__ = ["CatalogContext", "PRELOAD_PROMPT_RULES", "build_question_context", "compact_card", "estimate_tokens"]
