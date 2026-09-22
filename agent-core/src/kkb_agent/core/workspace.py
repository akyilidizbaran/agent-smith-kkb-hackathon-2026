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


@dataclass
class SourceTable:
    """Oturuma giren her tablonun donmuş kopyası (M11-T01, ADR-0059): ikinci yükleme birinciyi kaybettirmez."""

    id: str
    title: str
    frame: pd.DataFrame
    provenance: dict[str, QueryProvenance]


class AnalysisWorkspace:
    """Aktif analiz tablosu ve onun tam geçmişi."""

    MAX_SOURCES = 8

    def __init__(self) -> None:
        self._table: pd.DataFrame | None = None
        self._history: list[WorkspaceStep] = []
        self._snapshots: list[pd.DataFrame] = []
        self._column_sources: dict[str, QueryProvenance] = {}
        self.title: str = ""
        self._peeks: list[tuple[str, pd.DataFrame]] = []      # bakış sorguları (tabloyu değiştirmeyen)
        self.web_pages: dict[str, dict[str, object]] = {}     # url → sha256/fetched_at/status; turlar arası kalır
        self._sources: dict[str, SourceTable] = {}             # k1, k2, … — join ve workspace_query için
        self._source_seq = 0
        self.active_source_id: str | None = None

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
        """Okunan sayfa ve seçilmiş tablo metadatasını sonraki turların kanıt paneli için sakla."""
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
        self, df: pd.DataFrame, *, description: str, provenance: QueryProvenance | None = None,
        column_provenance: dict[str, QueryProvenance] | None = None,
    ) -> str:
        """Yeni bir analiz başlatır. Önceki tablo geçmişe alınır; tablo kimlikli kaynak olarak kaydedilir."""
        self._snapshot()
        self._table = df.copy()
        if provenance:
            for col in df.columns:
                self._column_sources[col] = provenance
        for col, prov in (column_provenance or {}).items():
            if prov is not None:
                self._column_sources[col] = prov
        self._record("set_table", description, provenance, columns_added=list(df.columns))
        return self._register_source(description)

    def replace_table(
        self,
        df: pd.DataFrame,
        *,
        description: str,
        column_provenance: dict[str, QueryProvenance | None] | None = None,
        columns_added: list[str] | None = None,
    ) -> None:
        """Replace the active frame while preserving column provenance.

        This is intentionally separate from :meth:`set_table`: a verified
        transformation may need to calculate on the full source window and
        publish a filtered view afterwards.  The operation remains one
        reversible workspace step and does not pretend that the filtered view
        was a new lakehouse retrieval.
        """
        if self._table is None:
            raise ValueError("Önce bir tablo oluşturulmalı (set_table).")
        self._snapshot()
        self._table = df.copy()
        for column, provenance in (column_provenance or {}).items():
            if provenance is not None:
                self._column_sources[str(column)] = provenance
        self._record("transform", description, None, columns_added=columns_added or [])
        self._register_source(description)

    # ---------- kimlikli kaynak tablolar (M11) ----------
    def _register_source(self, title: str) -> str:
        assert self._table is not None
        self._source_seq += 1
        sid = f"k{self._source_seq}"
        prov = {str(c): self._column_sources[c] for c in self._table.columns if c in self._column_sources}
        self._sources[sid] = SourceTable(id=sid, title=title or "tablo", frame=self._table.copy(), provenance=prov)
        while len(self._sources) > self.MAX_SOURCES:
            self._sources.pop(next(iter(self._sources)))
        self.active_source_id = sid
        return sid

    def sources(self) -> list[SourceTable]:
        return list(self._sources.values())

    def source(self, ref: str) -> SourceTable | None:
        """'aktif' güncel tabloyu (eklenen kolonlarla) verir; 'kN' yüklendiği andaki kopyayı."""
        if ref in ("aktif", "t", "active"):
            if self._table is None:
                return None
            prov = {str(c): self._column_sources[c] for c in self._table.columns if c in self._column_sources}
            return SourceTable(id="aktif", title=self.title or "aktif tablo", frame=self._table, provenance=prov)
        return self._sources.get(ref)

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

    def add_columns(
        self,
        values: dict[str, pd.Series],
        *,
        description: str,
        provenance_by_column: dict[str, QueryProvenance | None] | None = None,
    ) -> None:
        """Atomically add several derived columns as one workspace operation.

        Deterministic follow-up transformations often derive the same operation
        for several measures. One snapshot and one history record keep that
        operation reversible and let the answer layer project all derived
        columns together without pretending that each column was a separate
        model/tool turn.
        """
        if self._table is None:
            raise ValueError("Önce bir tablo oluşturulmalı (set_table).")
        if not values:
            raise ValueError("En az bir sütun eklenmeli.")
        names = list(values)
        duplicate = [name for name in names if name in self._table.columns]
        if duplicate:
            raise ValueError(f"Sütun(lar) zaten tabloda var: {', '.join(duplicate)}")

        self._snapshot()
        for name, series in values.items():
            self._table[name] = series.reindex(self._table.index)
            provenance = (provenance_by_column or {}).get(name)
            if provenance is not None:
                self._column_sources[name] = provenance
        first_provenance = next(
            (p for p in (provenance_by_column or {}).values() if p is not None), None
        )
        self._record("add_column", description, first_provenance, columns_added=names)

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
        if len(self._sources) > 1:
            lines.append("Oturumdaki tablolar (workspace_join ve workspace_query'de kimlikle kullan; aktif tablo `t`):")
            for src in self._sources.values():
                cols = ", ".join(map(str, list(src.frame.columns)[:8]))
                mark = " ← aktif tablonun kaynağı" if src.id == self.active_source_id else ""
                lines.append(f"  {src.id}: {src.title[:60]} — {len(src.frame)} satır; kolonlar: {cols}{mark}")
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
        # The active result title follows the current workspace state. Keeping
        # the initial retrieval title after a filter/transform made the UI
        # describe a 60-period source while exporting a 24-period derived view.
        if description:
            self.title = description
        self._history.append(
            WorkspaceStep(
                order=len(self._history) + 1,
                action=action,
                description=description,
                provenance=copy.copy(provenance),
                columns_added=columns_added or [],
            )
        )
