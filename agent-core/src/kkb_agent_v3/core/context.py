"""Katalog bağlamı — token bütçeli ön-yükleme (V3 §3.5, E8).

E8 ölçümü [EMP]: katalog ≤ ~6k token iken tamamı prompt'ta doğruluğu düşürmüyor
(%98, 0,6 s); üstünde hem yavaşlıyor hem hata artıyor. Blok C [EMP]: ön-yükleme
LLM turunu 6,9 → 3,9'a indirdi (keşif turları LLM turu olmaktan çıkıyor).

Bu modül kataloğu ölçer ve iki moddan birini seçer:
  full   : kartlar + kırılım kolonlarının gerçek değerleri prompt'a girer
  search : yalnız tek satırlık tablo dizini girer; model lakehouse_search /
           describe / distinct_values ile keşfeder (E8 eşik üstü modu)
"""

from __future__ import annotations

from dataclasses import dataclass

from kkb_agent.contracts.catalog import ColumnRole
from kkb_agent.contracts.lakehouse import LakehouseClient

from ..domain.loader import estimate_tokens


@dataclass(frozen=True)
class CatalogContext:
    text: str
    mode: str          # "full" | "search" | "empty"
    tokens: int
    datasets: int


def build_catalog_context(
    lakehouse: LakehouseClient, *, budget_tokens: int = 6000, max_values: int = 120, max_value_specs: int = 20
) -> CatalogContext:
    specs = lakehouse.list_datasets()
    if not specs:
        return CatalogContext(text="", mode="empty", tokens=0, datasets=0)

    parts: list[str] = []
    for spec in specs:
        parts.append(spec.to_prompt_card())
        # Seri-merkezli katalogda (Silver: her seri bir spec, binlerce olabilir) kırılım
        # değerlerini sorgulamak hem yavaş hem bütçeyi kesin aşar; yalnız küçük katalogda yapılır.
        if len(specs) > max_value_specs:
            continue
        for col in spec.columns:
            if col.role != ColumnRole.DIMENSION or col.dtype.upper() not in ("VARCHAR", "TEXT", "STRING"):
                continue
            has_flag = spec.column("is_alt_toplam") is not None
            select = f"{col.name}, is_alt_toplam" if has_flag else col.name
            try:
                res = lakehouse.execute_sql(
                    f"SELECT DISTINCT {select} FROM {spec.dataset_id} ORDER BY 1 LIMIT {max_values + 1}"
                )
            except Exception:  # noqa: BLE001 — değer listesi olmadan da kart yeterli
                continue
            df = res.data
            lines = [f"'{col.name}' kolonundaki GERÇEK değerler ({min(len(df), max_values)} adet; filtrede birebir kullan):"]
            for row in df.head(max_values).itertuples(index=False):
                flag = "   ⚠ ALT TOPLAM" if has_flag and bool(row[1]) else ""
                lines.append(f"  - {row[0]}{flag}")
            if len(df) > max_values:
                lines.append(f"  … (+{len(df) - max_values}; tam liste için lakehouse_distinct_values)")
            parts.append("\n".join(lines))
    full = "\n\n".join(parts)
    tokens = estimate_tokens(full)
    if tokens <= budget_tokens:
        return CatalogContext(text=full, mode="full", tokens=tokens, datasets=len(specs))

    index = "\n".join(
        f"- {s.dataset_id}: {s.name} [{s.frequency.value}, {s.coverage.start}→{s.coverage.end}]" for s in specs
    )
    text = (
        "TABLO DİZİNİ (katalog prompt bütçesini aşıyor; ayrıntı için lakehouse_describe ve "
        "kalem adları için lakehouse_distinct_values çağır):\n" + index
    )
    return CatalogContext(text=text, mode="search", tokens=estimate_tokens(text), datasets=len(specs))
