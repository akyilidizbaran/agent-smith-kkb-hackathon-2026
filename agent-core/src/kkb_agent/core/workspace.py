"""AnalysisWorkspace — konuşma boyunca yaşayan analiz durumu.

Neden var: Örnek senaryoda kullanıcı sırasıyla şunları istiyor:
    1) "konut kredisi + faiz tablosunu göster"
    2) "tabloyu bozmadan sadece kredi tutarlarını enflasyondan arındır"
    3) "bu tabloyu hiç bozmadan yeni bir sütun olarak konut fiyat endeksi ekle"

Her soruda sıfırdan sorgu üreten bir agent bu akışta başarısız olur: 2. adımda
tablonun şekli değişir, 3. adımda kullanıcının baktığı tablo kaybolur.
Bu yüzden tablo, konuşmanın kendisi kadar uzun yaşayan bir nesnedir. Agent
tabloyu yeniden üretmez; üzerinde AMELİYAT yapar.

Her işlem geçmişe kaydedilir, böylece hem geri alınabilir hem de
'bu sütun nereden geldi?' sorusu cevaplanabilir.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from ..contracts.lakehouse import QueryProvenance


@dataclass
class WorkspaceStep:
    """Tabloya uygulanan tek bir işlemin kaydı."""

    order: int
    action: str          # 'set_table' | 'add_column' | 'transform' | 'filter'
    description: str     # kullanıcıya gösterilecek Türkçe açıklama
    provenance: QueryProvenance | None = None
    columns_added: list[str] = field(default_factory=list)
    at: datetime = field(default_factory=datetime.now)


class AnalysisWorkspace:
    """Aktif analiz tablosu ve onun tam geçmişi."""

    def __init__(self) -> None:
        self._table: pd.DataFrame | None = None
        self._history: list[WorkspaceStep] = []
        self._snapshots: list[pd.DataFrame] = []
        self._column_sources: dict[str, QueryProvenance] = {}
        self.title: str = ""
        self._peeks: list[tuple[str, pd.DataFrame]] = []      # bakış sorguları (tabloyu değiştirmeyen)
        self.web_pages: dict[str, dict[str, object]] = {}     # url → sha256/fetched_at/status; turlar arası kalır

    # ---------- durum ----------
    @property
    def has_table(self) -> bool:
        return self._table is not None and not self._table.empty

    @property
    def table(self) -> pd.DataFrame | None:
        return self._table

    @property
    def history(self) -> list[WorkspaceStep]:
        return list(self._history)

    def columns(self) -> list[str]:
        return list(self._table.columns) if self._table is not None else []

    def note_peek(self, sql: str, frame: pd.DataFrame) -> None:
        """Bakış sorgusunun sonucu: tablo değişmez ama cevaptaki sayı buradan gelmiş olabilir."""
        self._peeks.append((sql, frame.copy()))
        if len(self._peeks) > 10:
            self._peeks.pop(0)

    def peeks(self) -> list[tuple[str, pd.DataFrame]]:
        return list(reversed(self._peeks))

    def remember_web(self, artifact: dict[str, object]) -> None:
        """web_url'in ziyaret ettiği sayfalar (sha256 + zaman) sonraki turların kanıt paneli için."""
        for v in artifact.get("visited", []) or []:
            url = v.get("url") if isinstance(v, dict) else None
            if url:
                self.web_pages[str(url)] = dict(v)

    def previous_tables(self) -> list[pd.DataFrame]:
        """Geçmişteki tablo sürümleri, en yeniden en eskiye (kanıt paneli için: cevaptaki sayı
        bakış modunda ya da tablo değişmeden önce üretilmiş olabilir)."""
        return list(reversed(self._snapshots))

    # ---------- işlemler ----------
    def set_table(
        self, df: pd.DataFrame, *, description: str, provenance: QueryProvenance | None = None
    ) -> None:
        """Yeni bir analiz başlatır. Önceki tablo geçmişe alınır."""
        self._snapshot()
        self._table = df.copy()
        if provenance:
            for col in df.columns:
                self._column_sources[col] = provenance
        self._record("set_table", description, provenance, columns_added=list(df.columns))

    def add_column(
        self,
        name: str,
        values: pd.Series,
        *,
        description: str,
        provenance: QueryProvenance | None = None,
        join_on: str | None = None,
    ) -> None:
        """Mevcut tabloyu BOZMADAN yeni sütun ekler.

        join_on verilirse hizalama o anahtar üzerinden yapılır — dönem
        kolonları birebir örtüşmese bile (haftalık/aylık karışımı) doğru
        satıra düşmesini sağlar.
        """
        if self._table is None:
            raise ValueError("Önce bir tablo oluşturulmalı (set_table).")
        self._snapshot()

        if join_on and join_on in self._table.columns:
            aligned = values.reindex(self._table[join_on].to_numpy())
            self._table[name] = aligned.to_numpy()
        else:
            self._table[name] = values.reindex(self._table.index)

        if provenance:
            self._column_sources[name] = provenance
        self._record("add_column", description, provenance, columns_added=[name])

    def replace_column(
        self,
        name: str,
        values: pd.Series,
        *,
        description: str,
        provenance: QueryProvenance | None = None,
        keep_original_as: str | None = None,
    ) -> None:
        """Bir sütunun değerlerini değiştirir (ör. enflasyondan arındırma).

        keep_original_as verilirse orijinal değerler ayrı sütunda korunur;
        kullanıcı 'reel mi nominal mi' karşılaştırması isteyebilir.
        """
        if self._table is None or name not in self._table.columns:
            raise ValueError(f"'{name}' sütunu tabloda yok.")
        self._snapshot()

        added: list[str] = []
        if keep_original_as:
            self._table[keep_original_as] = self._table[name]
            self._column_sources[keep_original_as] = self._column_sources.get(name)  # type: ignore[assignment]
            added.append(keep_original_as)

        self._table[name] = values.reindex(self._table.index)
        if provenance:
            self._column_sources[name] = provenance
        self._record("transform", description, provenance, columns_added=added)

    def revert(self) -> bool:
        """Son işlemi geri alır. 'Bu değişikliği iptal et' senaryosu için."""
        if not self._snapshots:
            return False
        self._table = self._snapshots.pop()
        if self._history:
            self._history.pop()
        return True

    # ---------- izlenebilirlik ----------
    def column_provenance(self, column: str) -> QueryProvenance | None:
        """'Bu sütundaki rakam nereden geliyor?' sorusunun cevabı."""
        return self._column_sources.get(column)

    def describe_for_llm(self, max_rows: int = 5) -> str:
        """Tablonun LLM'e verilecek kompakt özeti.

        Tablonun TAMAMI asla prompt'a konmaz — 60 aylık çok kırılımlı bir
        tablo context window'u tek başına doldurur. Model şemayı ve birkaç
        örnek satırı görür, hesabı DuckDB/pandas yapar.
        """
        if self._table is None:
            return "Aktif tablo yok."
        df = self._table
        lines = [
            f"Aktif tablo: {self.title or 'isimsiz'} — {len(df)} satır, {len(df.columns)} sütun",
            f"Sütunlar: {', '.join(f'{c} ({df[c].dtype})' for c in df.columns)}",
            f"İlk {min(max_rows, len(df))} satır:",
            df.head(max_rows).to_string(index=False),
        ]
        if self._history:
            lines.append("Bu tabloya uygulanan işlemler:")
            lines += [f"  {s.order}. {s.description}" for s in self._history]
        return "\n".join(lines)

    # ---------- iç ----------
    def _snapshot(self) -> None:
        if self._table is not None:
            self._snapshots.append(self._table.copy())
            # Bellek kontrolü: uzun konuşmalarda sınırsız geçmiş tutmayalım.
            if len(self._snapshots) > 20:
                self._snapshots.pop(0)

    def _record(
        self,
        action: str,
        description: str,
        provenance: QueryProvenance | None,
        columns_added: list[str] | None = None,
    ) -> None:
        self._history.append(
            WorkspaceStep(
                order=len(self._history) + 1,
                action=action,
                description=description,
                provenance=copy.copy(provenance),
                columns_added=columns_added or [],
            )
        )
