"""Kanıt paneli inşacısı — cevaptaki sayıdan kaynak baytlarına, tahminsiz (ADR-0033).

Zincir dört halkadan kurulur ve her halka kendi katmanından okunur:

1. **sayı → hücre**: anlatı doğrulamanın sayı ayrıştırıcısı (`grounding.numbers_in`) ile
   cevaptaki her sayı tabloda aranır; eşleşen hücrenin kolonu ve satır anahtarı yazılır.
2. **hücre → SQL**: kolonun workspace provenance'ı (hangi SQL, hangi seri, hangi kaynak).
3. **satır → artifact**: tablo satırının dönem değeri + provenance'taki seri kimliği ile
   Silver/adhoc gözlemi bulunur; gözlem `artifact_sha256`, `run_id`, `vintage_id` taşır.
   Gold çerçevelerinde satır zaten `artifact_sha256_list` ve `source_observation_dates`
   taşır; oradan okunur.
4. **artifact → RAW/Bronze/URL**: `meta.artifact` (locator, fetched_at, http_status, raw_path)
   ve diskteki Bronze parquet.

Halka yoksa uydurulmaz: `gaps` listesi neresinin kopuk olduğunu söyler. Seed adaptöründe
artifact yoktur; zincir SQL'de biter ve bunu söyler.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import pandas as pd

from ..contracts.evidence import (
    ColumnEvidence, EvidenceCapable, EvidencePanel, NumberEvidence, ObservationEvidence,
)
from ..contracts.lakehouse import LakehouseError
from .grounding import _NUM_RE, numbers_in
from .workspace import AnalysisWorkspace

_DATE_PREFERENCE = ("period_end", "observation_date", "donem", "dönem", "tarih", "date")


def _is_datelike(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    values = series.dropna()
    return not values.empty and all(hasattr(v, "year") for v in values.head(20))


def _from_web(c: ColumnEvidence) -> bool:
    """web_url kaynağı 'web — <başlık>' diye yazar; kırpılmış tablo bunu olduğu gibi taşır."""
    return any(str(src).startswith("web") for src in c.sources)


def _text_cells_as_numbers(table: pd.DataFrame) -> dict[str, pd.Series]:
    """Metin kolonlarında tek sayı taşıyan hücreler → float serisi (Türkçe binlik/ondalık dilbilgisi)."""
    out: dict[str, pd.Series] = {}
    for col in table.columns:
        if pd.api.types.is_numeric_dtype(table[col]) or pd.api.types.is_datetime64_any_dtype(table[col]):
            continue
        values = []
        any_number = False
        for v in table[col].tolist():
            nums = numbers_in(str(v)) if isinstance(v, str) and v.strip() else []
            if len(nums) == 1:
                values.append(nums[0]); any_number = True
            else:
                values.append(float("nan"))
        if any_number:
            out[str(col)] = pd.Series(values, index=table.index, dtype="float64")
    return out


def _time_column(table: pd.DataFrame) -> str | None:
    datelike = [str(c) for c in table.columns if _is_datelike(table[c])]
    for name in _DATE_PREFERENCE:
        for c in datelike:
            if c.rsplit("::", 1)[-1].lower() == name:
                return c
    return datelike[0] if datelike else None


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _key_text(value: Any) -> str:
    d = _as_date(value)
    return d.isoformat() if d is not None else str(value)


def _number_texts(answer: str) -> list[tuple[str, float]]:
    """Metindeki sayılar, göründükleri yazımla; `numbers_in` ile aynı ayrıştırma."""
    out: list[tuple[str, float]] = []
    for m in _NUM_RE.finditer((answer or "").replace("\u2212", "-")):
        raw = m.group(0)
        parsed = numbers_in(raw)
        if parsed:
            out.append((raw, parsed[0]))
    return out


class EvidenceBuilder:
    """Cevap + workspace + adaptör → `EvidencePanel`. Hata cevabı asla düşürmez."""

    def __init__(self, lakehouse: Any, *, tolerance: float = 0.005, max_rows: int = 200) -> None:
        self.lakehouse = lakehouse
        self.tolerance = tolerance
        self.max_rows = max_rows

    # ------------------------------------------------------------------ halkalar
    def _match_numbers(self, answer: str, table: pd.DataFrame, time_col: str | None,
                       previous: list[pd.DataFrame] | None = None,
                       peeks: list[tuple[str, pd.DataFrame]] | None = None,
                       question: str = "") -> list[NumberEvidence]:
        numeric_cols = [c for c in table.columns if pd.api.types.is_numeric_dtype(table[c])]
        # Soruda geçen sayı (yıl, dönem) cevapta yankılanır; anlatı doğrulamayla aynı kural.
        asked = {n for _, n in _number_texts(question or "")}
        # Metin kalmış hücreler (sayı biçimi belirsiz: "13.837") de sayıdır; Türkçe dilbilgisiyle
        # okunup karşılaştırılır (ölçüldü, G18b: model kartı aynen yazdı, panel "tabloda yok" dedi).
        text_parsed = _text_cells_as_numbers(table)
        out: list[NumberEvidence] = []
        seen: set[str] = set()
        for text, number in _number_texts(answer):
            if text in seen:
                continue
            seen.add(text)
            ev = NumberEvidence(number=number, text=text)
            if number in asked:
                ev.matched, ev.column, ev.row_key = True, "(soruda geçiyor)", text
                out.append(ev)
                continue
            # yıl/ay gibi tarih parçaları sayı değildir: dönem kolonunun yılı ile eşleşiyorsa geç
            if time_col is not None and float(number).is_integer() and 1900 <= number <= 2100:
                years = {d.year for d in table[time_col].map(_as_date).dropna()}
                if int(number) in years:
                    ev.matched, ev.column, ev.row_key = True, time_col, f"yıl {int(number)}"
                    out.append(ev)
                    continue
            if float(number).is_integer() and 1 <= number <= 31 and len(str(text)) <= 2:
                continue  # gün/ay numarası ya da sıra sayısı; anlatı doğrulama da bunları saymaz
            # Satır sayısı da araç çıktısındandır ("124 hafta", "66 ay"): tablo ya da önceki sürüm.
            if float(number).is_integer() and int(number) in {len(table), *(len(o) for o in (previous or []))}:
                ev.matched, ev.column, ev.row_key = True, "(satır sayısı)", f"{int(number)} satır"
                out.append(ev)
                continue
            for col in numeric_cols:
                series = table[col]
                hits = series[(series - number).abs() <= max(abs(number) * self.tolerance, 1e-9)]
                if not hits.empty:
                    idx = int(hits.index[0])
                    ev.matched, ev.column, ev.row_index = True, str(col), idx
                    ev.row_key = _key_text(table.loc[idx, time_col]) if time_col else str(idx)
                    break
            if not ev.matched:
                for col, series in text_parsed.items():
                    hits = series[(series - number).abs() <= max(abs(number) * self.tolerance, 1e-9)]
                    if not hits.empty:
                        idx = int(hits.index[0])
                        ev.matched, ev.column, ev.row_index = True, col, idx
                        ev.row_key = (_key_text(table.loc[idx, time_col]) if time_col else str(idx)) + " (metin hücre)"
                        break
            if not ev.matched:
                # Önceki tablo sürümleri: sayı, tablo bakış moduyla ya da kırpılmadan önce üretilmiş
                # olabilir (ölçüldü: 24 satırlık nüfus tablosu sonradan 5 satıra kırpıldı; cevaptaki
                # 72 sayının 45'i "tabloda yok" görünüyordu). Araç çıktısından gelen sayı sayıdır.
                for depth, old in enumerate(previous or [], start=1):
                    found = False
                    for col in [c for c in old.columns if pd.api.types.is_numeric_dtype(old[c])]:
                        series = old[col]
                        hits = series[(series - number).abs() <= max(abs(number) * self.tolerance, 1e-9)]
                        if not hits.empty:
                            ev.matched, ev.column, ev.row_key = True, str(col), f"önceki tablo (-{depth})"
                            found = True
                            break
                    if found:
                        break
            if not ev.matched:
                # Bakış sorgusu sonuçları (aktif tabloyu değiştirmeyen özetler: toplam yüzde, en yüksek yıl).
                for sql, frame in (peeks or []):
                    found = False
                    for col in [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]:
                        series = frame[col]
                        hits = series[(series - number).abs() <= max(abs(number) * self.tolerance, 1e-9)]
                        if not hits.empty:
                            ev.matched, ev.column, ev.row_key = True, str(col), f"bakış sorgusu: {sql[:80]}"
                            found = True
                            break
                    if found:
                        break
            if not ev.matched and number != 0:
                # İşaret yazımı: model "−2,31" (Unicode eksi) ya da "%-2,31" yazınca ayrıştırıcı
                # işareti düşürür; değer tabloda ters işaretle varsa sayı yine araçtandır (ölçüldü, G15/G17).
                frames = [table, *(previous or []), *[f for _, f in (peeks or [])]]
                for frame in frames:
                    hit_col = next(
                        (str(c) for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])
                         and not frame[c][(frame[c] + number).abs() <= max(abs(number) * self.tolerance, 1e-9)].empty),
                        None,
                    )
                    if hit_col:
                        ev.matched, ev.column, ev.row_key = True, hit_col, "işaret yazımı (−)"
                        break
            out.append(ev)
        return out

    def _columns(self, workspace: AnalysisWorkspace, table: pd.DataFrame) -> list[ColumnEvidence]:
        out: list[ColumnEvidence] = []
        for col in table.columns:
            prov = workspace.column_provenance(str(col))
            out.append(ColumnEvidence(
                column=str(col), sql=prov.sql if prov else None,
                dataset_ids=list(prov.dataset_ids) if prov else [],
                sources=list(prov.sources) if prov else [],
                source_urls=list(prov.source_urls) if prov else [],
                executed_at=prov.executed_at if prov else None,
                warnings=list(prov.warnings) if prov else [],
            ))
        return out

    def _observations(
        self, table: pd.DataFrame, columns: list[ColumnEvidence], time_col: str | None, gaps: list[str]
    ) -> tuple[list[ObservationEvidence], dict[str, dict[str, Any]]]:
        lake = self.lakehouse
        if not isinstance(lake, EvidenceCapable):
            gaps.append("adaptör artifact izi sunmuyor (seed): zincir SQL'de biter")
            return [], {}
        observations: list[ObservationEvidence] = []
        artifacts: dict[str, dict[str, Any]] = {}
        head = table.head(self.max_rows)

        # Gold çerçevesi: satır kendi kanıtını taşır.
        sha_cols = [c for c in head.columns if str(c).rsplit("::", 1)[-1] == "artifact_sha256_list"]
        if sha_cols:
            shas: list[str] = []
            for c in sha_cols:
                for cell in head[c].dropna():
                    shas.extend(str(s) for s in (cell if isinstance(cell, (list, tuple)) else [cell]))
            try:
                artifacts = lake.evidence_for_artifacts(sorted(set(shas)))
            except LakehouseError as exc:
                gaps.append(f"artifact izi okunamadı: {exc}")
            # kaynak gözlemler: series (önekten ya da provenance'tan) + source_observation_dates
            date_cols = [c for c in head.columns if str(c).rsplit("::", 1)[-1] == "source_observation_dates"]
            dataset_ids = sorted({d for col in columns for d in col.dataset_ids})
            for c in date_cols:
                prefix = str(c).split("::", 1)[0].split("@", 1)[0] if "::" in str(c) else None
                series_ids = [prefix] if prefix else dataset_ids
                dates: list[date] = []
                for cell in head[c].dropna():
                    for d in (cell if isinstance(cell, (list, tuple)) else [cell]):
                        parsed = _as_date(d) or (date.fromisoformat(str(d)[:10]) if str(d)[:4].isdigit() else None)
                        if parsed:
                            dates.append(parsed)
                for sid in series_ids:
                    try:
                        observations.extend(lake.evidence_for_observations(sid, sorted(set(dates))))
                    except LakehouseError as exc:
                        gaps.append(f"{sid}: gözlem izi okunamadı: {exc}")
            if not observations and not artifacts:
                gaps.append("Gold satırları artifact listesi taşıyor ama hiçbiri çözülemedi")
            return observations, artifacts

        # Türetilmiş kolonlar (formül) zinciri kırmaz: kaynak kolonlar üzerinden devam eder.
        columns = [c for c in columns if not (c.sql or "").startswith("türetilmiş:")]
        if not columns:
            return [], {}
        # Web tablosu: zincir sayfanın baytlarında biter (URL + sha256 + zaman); gözlem aranmaz.
        # workspace_query ile kırpılmış web tablosu da web tablosudur: kaynak kolonların provenance'ı
        # taşınır (sources=web, dataset_ids boş). Ölçüldü: kırpma ve türetilmiş kolon sonrası zincir
        # yanlışlıkla "dönem kolonu yok" diye kopuk görünüyordu.
        def _web_col(c: ColumnEvidence) -> bool:
            sql = c.sql or ""
            return sql.startswith("web_url ") or (
                sql.startswith("workspace_query:") and not c.dataset_ids and _from_web(c)
            )
        if all(_web_col(c) for c in columns):
            return [], {}

        # Silver sorgusu: dönem + provenance'taki seri(ler).
        if time_col is None:
            gaps.append("tabloda dönem kolonu yok; satırlar gözleme bağlanamadı")
            return [], {}
        dates = sorted({d for d in head[time_col].map(_as_date).dropna()})
        dataset_ids = sorted({d for col in columns for d in col.dataset_ids})
        if not dataset_ids:
            gaps.append("kolon provenance'ında seri kimliği yok")
            return [], {}
        entity_col = next((c for c in head.columns if str(c) == "entity_id"), None)
        entities = sorted({str(e) for e in head[entity_col].dropna()}) if entity_col else [None]
        for sid in dataset_ids:
            for ent in entities:
                try:
                    observations.extend(lake.evidence_for_observations(sid, dates, entity_id=ent))
                except LakehouseError as exc:
                    gaps.append(f"{sid}: gözlem izi okunamadı: {exc}")
        if observations:
            try:
                artifacts = lake.evidence_for_artifacts(sorted({o.artifact_sha256 for o in observations}))
            except LakehouseError as exc:
                gaps.append(f"artifact izi okunamadı: {exc}")
        else:
            gaps.append("provenance'taki seriler için dönemlere karşılık gözlem bulunamadı")
        return observations, artifacts

    @staticmethod
    def _web(panel: EvidencePanel, artifacts: list[dict[str, Any]], workspace: AnalysisWorkspace | None = None) -> None:
        """Kullanılan sayfa kaynak; taranıp kullanılmayan ve erişilemeyen sayfalar panelde.
        Sayfa önceki turda çekildiyse (tablo hâlâ o sayfadan) workspace'in hatırladığı sha256+zaman kullanılır."""
        if workspace is not None and not any(a.get("kind") == "web" for a in artifacts):
            urls: list[str] = []
            for c in panel.columns:
                if _from_web(c):
                    urls.extend(u for u in c.source_urls if u not in urls)
            for u in urls:
                v = workspace.web_pages.get(u)
                if v:
                    entry = {"url": u, "sha256": v.get("sha256"), "fetched_at": v.get("fetched_at"),
                             "status": v.get("status"), "title": v.get("title"),
                             **({"ocr": v.get("ocr")} if v.get("ocr") else {})}
                    if entry not in panel.web_sources:
                        panel.web_sources.append(entry)
        for art in artifacts:
            if art.get("kind") != "web":
                continue
            used = art.get("used")
            for v in art.get("visited", []):
                entry = {"url": v.get("url"), "sha256": v.get("sha256"), "fetched_at": v.get("fetched_at"),
                         "status": v.get("status"), "title": v.get("title"),
                         **({"ocr": v.get("ocr")} if v.get("ocr") else {})}
                if used and v.get("url") == used:
                    if entry not in panel.web_sources:
                        panel.web_sources.append(entry)
                else:
                    panel.web_unused.append({**entry, "note": "tarandı, tabloya girmedi"})
            for b in art.get("blocked", []):
                panel.web_unused.append({"url": b.get("url"), "note": f"erişilemedi: {b.get('status')} / {b.get('reason')}"})
            for url, reason in art.get("skipped", [])[:10]:
                panel.web_unused.append({"url": url, "note": f"atlandı: {reason}"})

    # ------------------------------------------------------------------ giriş
    def build(
        self, question: str, answer: str, workspace: AnalysisWorkspace, steps: list[Any],
        *, artifacts: list[dict[str, Any]] | None = None,
    ) -> EvidencePanel:
        panel = EvidencePanel(question=question, supports_artifacts=isinstance(self.lakehouse, EvidenceCapable))
        table = workspace.table
        if table is None or table.empty:
            panel.gaps.append("analiz tablosu yok")
            panel.numbers = [NumberEvidence(number=n, text=t) for t, n in _number_texts(answer)]
            return panel
        panel.table_rows = len(table)
        time_col = _time_column(table)
        panel.numbers = self._match_numbers(answer, table, time_col, previous=workspace.previous_tables(),
                                            peeks=workspace.peeks(), question=question)
        panel.columns = self._columns(workspace, table)
        panel.observations, panel.artifacts = self._observations(table, panel.columns, time_col, panel.gaps)

        used = {d for c in panel.columns for d in c.dataset_ids}
        consulted = []
        for s in steps:
            if getattr(s, "tool_name", None) in ("lakehouse_describe", "lakehouse_distinct_values"):
                ds = (getattr(s, "tool_args", {}) or {}).get("dataset_id")
                if ds and ds not in used and ds not in consulted:
                    consulted.append(ds)
        panel.consulted_unused = consulted
        panel.chart_paths = [str(a.get("png_path") or a.get("spec_path")) for a in (artifacts or [])
                             if a and a.get("kind") != "web"]
        self._web(panel, artifacts or [], workspace)
        unmatched = [n.text for n in panel.numbers if not n.matched]
        if unmatched:
            panel.gaps.append("tabloda bulunmayan sayılar: " + ", ".join(unmatched[:8]))
        for c in panel.columns:
            if c.sql is None:
                panel.gaps.append(f"'{c.column}' kolonunun provenance kaydı yok")
        if panel.supports_artifacts:
            incomplete = [o for o in panel.observations if not o.complete]
            if incomplete:
                panel.gaps.append(f"{len(incomplete)} gözlemin artifact/locator/fetched_at izi eksik")
        return panel


__all__ = ["EvidenceBuilder"]
