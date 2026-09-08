"""Lakehouse Contract — agent katmanı ile veri katmanı arasındaki tek sınır.

Agent tarafı Lakehouse'un NASIL kurulduğunu bilmez ve bilmemelidir.
Parquet+Iceberg, Delta ya da düz DuckDB olması agent'ı ilgilendirmez;
sadece bu Protocol'ün karşılanması gerekir.

Bu sayede:
  - Veri ekibi ve agent ekibi paralel çalışabilir (bekleme yok).
  - Yarışmanın 'jenerik olmalı, içi boşaltılıp sağlık verisiyle çalışabilmeli'
    şartı mimari düzeyde sağlanır: yeni bir alan için sadece yeni bir
    LakehouseClient implementasyonu + yeni katalog yazılır, agent aynı kalır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import pandas as pd

from .catalog import DatasetSpec


@dataclass
class QueryProvenance:
    """'Güven katmanı: Kaynak gösterimi – İzlenebilirlik – Doğruluk Kontrolü'
    slaytının kod karşılığı.

    Üretilen HER sayı bu kayıtla birlikte taşınır. Demoda 'bu rakam nereden
    geliyor?' sorusuna saniyeler içinde cevap verebilmemizi sağlar.
    """

    sql: str
    dataset_ids: list[str]
    sources: list[str] = field(default_factory=list)       # 'BDDK Aylık Bülten Tablo 5'
    source_urls: list[str] = field(default_factory=list)
    row_count: int = 0
    executed_at: datetime = field(default_factory=datetime.now)
    duration_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{self.row_count} satır", f"kaynak: {', '.join(self.sources) or '—'}"]
        if self.warnings:
            parts.append(f"uyarı: {'; '.join(self.warnings)}")
        return " | ".join(parts)


@dataclass
class QueryResult:
    """Bir sorgunun sonucu — veri + nereden geldiği."""

    data: pd.DataFrame
    provenance: QueryProvenance

    @property
    def is_empty(self) -> bool:
        return self.data.empty


class LakehouseError(Exception):
    """Sorgu/katalog hatalarında fırlatılır. Agent bu hatayı görüp
    kendini onarabilmeli (SQL'i düzeltip yeniden denemeli)."""


@runtime_checkable
class LakehouseClient(Protocol):
    """Veri ekibinin sağlaması gereken arayüz.

    NOT (veri ekibi için): Bu Protocol'ü miras almanız gerekmez; aynı
    imzalara sahip bir sınıf yazmanız yeterlidir (structural typing).
    """

    # ---------- Katalog / keşif ----------
    def list_datasets(self) -> list[DatasetSpec]:
        """Lakehouse'daki tüm analiz-hazır tabloların tanımı."""
        ...

    def get_dataset(self, dataset_id: str) -> DatasetSpec:
        """Tek bir tablonun tanımı. Yoksa LakehouseError."""
        ...

    def search_datasets(self, query: str, limit: int = 5) -> list[DatasetSpec]:
        """Doğal dil sorgusuna en uygun tabloları döndürür.

        Katalog büyüdükçe tamamını prompt'a sığdıramayız; agent önce burayı
        çağırıp aday tabloları daraltır. Başlangıçta anahtar kelime eşleşmesi
        yeterli; ileride Kloudeks embedding + reranker ile değiştirilebilir.
        """
        ...

    # ---------- Sorgulama ----------
    def execute_sql(self, sql: str, *, max_rows: int = 10_000) -> QueryResult:
        """Salt-okunur SQL çalıştırır ve sonucu provenance ile döndürür.

        Uygulama SADECE okuma yapmalı; DDL/DML reddedilmelidir.
        """
        ...

    def preview(self, dataset_id: str, n: int = 5) -> QueryResult:
        """Tablodan örnek satırlar — agent'ın veriyi 'görmesi' için."""
        ...

    # ---------- Sağlık ----------
    def health(self) -> dict[str, Any]:
        """Bağlantı durumu, tablo sayısı, son yenilenme zamanı."""
        ...
