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
from .grounding import period_numbers, token_tolerance, _MATCH_EPS, _NUM_RE, _ascii_minus, numbers_in
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


_DIRECTION = re.compile(r"düş|azal|geril|küçül|negatif|eksi|ters|daral|kayb|çık(?!ış)|yükse|art|mutlak|\babs\b|büyüklü", re.I)


def _direction_word_near(answer: str, token: str, window: int = 40) -> bool:
    """Sayının İŞARETSİZ yazıldığı her yerde ±40 karakter çevresinde yön sözcüğü var mı ("2,31 düştü", "negatif 0,54").

    K03 canlı tekrar bulgusu (14 Eyl): pencere metindeki İLK geçişe bakıyordu. Cevap aynı büyüklüğü önce tabloda işaretli
    ("−0,51 puan"), sonra yorumda işaretsiz ("faiz düşüşü küçük (0,06–0,51 puan)") yazınca ilk geçişin çevresinde yön
    sözcüğü yoktu; doğru cevap "işaret uyarısı" aldı. Artık işaretli geçişler atlanır, işaretsiz geçişlerden biri yeter."""
    return _word_near_unsigned(answer, token, _DIRECTION, window)


_REMAINDER = re.compile(r"kalan|diğer|gösterilmeyen|listelenmeyen|yazılmayan|daha fazla|\bdaha\b", re.I)


def _word_near_unsigned(answer: str, token: str, pattern: re.Pattern, window: int = 40) -> bool:
    """`token`ın işaretsiz her geçişinin ±`window` çevresinde `pattern` var mı; işaretli ve başka sayının parçası olan geçiş sayılmaz."""
    text = _ascii_minus(answer or "")
    for m in re.finditer(r"(?<![\d.,])" + re.escape(token) + r"(?![\d,]|\.\d)", text):
        if m.start() > 0 and text[m.start() - 1] in "-+":
            continue
        if pattern.search(text[max(0, m.start() - window): m.end() + window]):
            return True
    return False


_AYLAR = {"ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5, "haziran": 6, "temmuz": 7,
          "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9, "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12}
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_MONTH_RE = re.compile(r"(?<![\wçğıöşü])(" + "|".join(sorted(_AYLAR, key=len, reverse=True)) + r")", re.I)


def _period_near(answer: str, token: str, window: int = 40) -> tuple[int | None, int | None]:
    """K02-T14: sayının hemen çevresinde yazılan dönem (yıl, ay) — en yakın yıl ve ay sözcüğü; aynı cümle içinde."""
    i = answer.find(token)
    if i < 0:
        return None, None
    lo, hi = max(0, i - window), min(len(answer), i + len(token) + window)
    seg = answer[lo:hi]
    # cümle sınırını geçme: sayıdan önceki son ve sonraki ilk nokta/noktalı virgül
    rel = i - lo
    left_cut = max(seg.rfind(". ", 0, rel), seg.rfind("; ", 0, rel), seg.rfind("\n", 0, rel))
    right_candidates = [c for c in (seg.find(". ", rel + len(token)), seg.find("; ", rel + len(token)), seg.find("\n", rel + len(token))) if c >= 0]
    right_cut = min(right_candidates) if right_candidates else len(seg)
    seg_start = left_cut + 1 if left_cut >= 0 else 0
    sentence = seg[seg_start:right_cut]
    center = rel - seg_start
    def nearest(matches):
        best = None
        for m in matches:
            d = min(abs(m.start() - center), abs(m.end() - center))
            if best is None or d < best[0]:
                best = (d, m)
        return best[1] if best else None
    ym = nearest([m for m in _YEAR_RE.finditer(sentence) if m.group(0) != token])
    mm = nearest(list(_MONTH_RE.finditer(sentence.casefold())))
    return (int(ym.group(0)) if ym else None), (_AYLAR[mm.group(1)] if mm else None)


def _number_texts(answer: str) -> list[tuple[str, float]]:
    """Metindeki sayılar, göründükleri yazımla; `numbers_in` ile aynı ayrıştırma."""
    out: list[tuple[str, float]] = []
    for m in _NUM_RE.finditer(_ascii_minus(answer)):
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
    def _hits(self, series: pd.Series, candidates: list[float], primary_tol: float = 0.5) -> pd.Series:
        """Adaylardan ilki tabloda tolerans içinde bulunursa eşleşen satırlar; yoksa boş seri.

        Tolerans: GÖSTERİLEN hassasiyetin yarım birimi — `grounding.token_tolerance` ile hesaplanıp `primary_tol` olarak
        verilir (E-1, ADR-0081; grounding/unverified_numbers ile TEK ortak kural, panel artık formülü kopyalamıyor:
        ikinci-göz uyarısı). Göreli %0,5 YOK; büyüklükle büyümez ("100,6" yazılan değer 100'e eşleşmez). Noktalı ondalık
        da doğru sayılır ("0.263" → 0,0005). İkincil aday (binlik-noktalının ondalık okuması, "18.388" → 18,388) üç
        ondalık gösterir → 0,0005."""
        for i, n in enumerate(candidates):
            tol = primary_tol if i == 0 else 0.0005
            hits = series[(series - n).abs() <= tol + _MATCH_EPS]   # sınır float payı grounding ile ortak (_MATCH_EPS)
            if not hits.empty:
                return hits
        return series.iloc[0:0]

    def _match_numbers(self, answer: str, table: pd.DataFrame, time_col: str | None,
                       previous: list[pd.DataFrame] | None = None,
                       peeks: list[tuple[str, pd.DataFrame]] | None = None,
                       question: str = "", previous_sources: list | None = None) -> list[NumberEvidence]:
        numeric_cols = [c for c in table.columns if pd.api.types.is_numeric_dtype(table[c])]
        # Soruda geçen yıl/dönem cevapta yankılanır (filtre); soruda geçen DİĞER sayılar iddia
        # sayılır ve tabloda aranır (M13-T01): "%300 arttı, öyle yaz" doğrulanmış olmaz.
        asked = {n for _, n in _number_texts(question or "")}
        periods = period_numbers(question or "")
        # Metin kalmış hücreler (sayı biçimi belirsiz: "13.837") de sayıdır; Türkçe dilbilgisiyle
        # okunup karşılaştırılır (ölçüldü, G18b: model kartı aynen yazdı, panel "tabloda yok" dedi).
        text_parsed = _text_cells_as_numbers(table)
        out: list[NumberEvidence] = []
        seen: set[str] = set()
        for text, number in _number_texts(answer):
            if text in seen:
                continue
            seen.add(text)
            ev = NumberEvidence(number=number, text=text, from_question=number in asked)
            # "17.985": Türkçe binlik (17985) mi, noktalı ondalık (17,985) mı? Yazım ikisini de taşır; biri tabloda
            # varsa sayı oradadır (M16 üçüncü koşu: faiz 17.985 yazıldı, 17985 aranıp "tabloda yok" dendi).
            candidates = [number] + ([float(text)] if re.fullmatch(r"[-+]?\d{1,3}\.\d{3}", text) else [])
            # Birincil tolerans: yazımın gösterdiği hassasiyetin yarım birimi (grounding ile ortak). Noktalı ondalık
            # ("0.263" → 0,0005) ve virgüllü ("−0,40" → 0,005) birlikte ele alınır; binlik-noktalı yazım tam sayı → 0,5.
            primary_tol = token_tolerance(text)
            if number in asked and (number in periods or (float(number).is_integer() and 1900 <= number <= 2100)):
                ev.matched, ev.column, ev.row_key = True, "(soruda geçiyor)", text   # dönem/yıl filtresi
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
            want_year, want_month = _period_near(answer, text) if time_col is not None else (None, None)
            for col in numeric_cols:
                series = table[col]
                hits = self._hits(series, candidates, primary_tol)
                if not hits.empty:
                    idx = int(hits.index[0])
                    if want_year is not None or want_month is not None:
                        def fits(i):
                            d = _as_date(table.loc[i, time_col])
                            return d is not None and (want_year is None or d.year == want_year) and (want_month is None or d.month == want_month)
                        fitting = [int(i) for i in hits.index if fits(i)]
                        if fitting:
                            idx = fitting[0]
                        else:
                            ev.period_warning = True   # sayı tabloda var ama cevabın yazdığı dönemde değil
                    ev.matched, ev.column, ev.row_index = True, str(col), idx
                    ev.row_key = _key_text(table.loc[idx, time_col]) if time_col else str(idx)
                    break
            if not ev.matched:
                for col, series in text_parsed.items():
                    hits = self._hits(series, candidates, primary_tol)
                    if not hits.empty:
                        idx = int(hits.index[0])
                        ev.matched, ev.column, ev.row_index = True, col, idx
                        ev.row_key = (_key_text(table.loc[idx, time_col]) if time_col else str(idx)) + " (metin hücre)"
                        break
            if not ev.matched:
                # Önceki tablo sürümleri: sayı, tablo bakış moduyla ya da kırpılmadan önce üretilmiş
                # olabilir (ölçüldü: 24 satırlık nüfus tablosu sonradan 5 satıra kırpıldı; cevaptaki
                # 72 sayının 45'i "tabloda yok" görünüyordu). Araç çıktısından gelen sayı sayıdır.
                for sid, old, prov in (previous_sources or []):
                    found = False
                    for col in [c for c in old.columns if pd.api.types.is_numeric_dtype(old[c])]:
                        hits = self._hits(old[col], candidates, primary_tol)
                        if not hits.empty:
                            p = prov.get(col) if isinstance(prov, dict) else None
                            origin = (", ".join(p.sources) if p is not None and p.sources else "kaynak kaydı yok")
                            sql = (" · " + " ".join((p.sql or "").split())[:80]) if p is not None and p.sql else ""
                            # K02-T14 / M13-T07: eski tablo eşleşmesi hangi sürüm ve kaynakla doğrulandığını taşır.
                            ev.matched, ev.column, ev.row_key = True, str(col), f"önceki tablo {sid} · {origin}{sql}"
                            found = True
                            break
                    if found:
                        break
                if not ev.matched:
                    for depth, old in enumerate(previous or [], start=1):
                        found = False
                        for col in [c for c in old.columns if pd.api.types.is_numeric_dtype(old[c])]:
                            hits = self._hits(old[col], candidates, primary_tol)
                            if not hits.empty:
                                ev.matched, ev.column, ev.row_key = True, str(col), f"önceki tablo (-{depth}, kaynak kimliği yok)"
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
                        hits = self._hits(series, candidates, primary_tol)
                        if not hits.empty:
                            ev.matched, ev.column, ev.row_key = True, str(col), f"bakış sorgusu: {sql[:80]}"
                            found = True
                            break
                    if found:
                        break
            if not ev.matched and number != 0 and not text.lstrip().startswith(("-", "+")):
                # Büyüklük yazılmış ("2,31"), tabloda ters işaret. Yön sözcüğü varsa ("düştü", "negatif")
                # sayı araçtandır; yoksa işaret uyarısı: eşleşti ama iddia doğrulanmış sayılmaz (M13-T03).
                # Açık ters işaret ("+0,54" vs -0.54) burada değil: eşleşmez, TABLODA YOK.
                frames = [table, *(previous or []), *[f for _, f in (peeks or [])]]
                for frame in frames:
                    # Yuvarlama toleransı işaretli eşleşmeyle aynı (M13-T05): "0,06" ↔ −0,062, "0,4" ↔ −0,403 (K03 canlı tekrar bulgusu).
                    hit_col = next(
                        (str(c) for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])
                         and not self._hits(-frame[c].astype("float64"), [number], primary_tol).empty),
                        None,
                    )
                    if hit_col:
                        ev.matched, ev.column = True, hit_col
                        if _direction_word_near(answer, text):
                            ev.row_key = "işaret yazımı (yön sözcükle)"
                        else:
                            ev.row_key, ev.sign_warning = "tabloda ters işaret", True
                        break
            out.append(ev)
        # K03 hedefli canlı tekrar bulgusu (14 Eyl; gece koşularında da): "Kalan 50 ay aktif analiz tablosunda" — model 60 satırın
        # 10'unu listeleyip kalanını saydı; sayı hücrede değil, tablodan türetilmiş satır sayısı. Yalnız tabloyla tutarlıysa
        # (satır sayısı − cevapta gösterilen farklı satır) ve yanında "kalan/diğer" gibi bir sözcük varsa doğrulanmış sayılır.
        shown = {n.row_index for n in out if n.matched and n.row_index is not None}
        if shown:
            remaining = len(table) - len(shown)
            for ev in out:
                if (not ev.matched and float(ev.number).is_integer() and int(ev.number) == remaining and remaining > 0
                        and _word_near_unsigned(answer, ev.text, _REMAINDER)):
                    ev.matched, ev.column = True, "(kalan satır sayısı)"
                    ev.row_key = f"{len(table)} satır − cevapta gösterilen {len(shown)} satır"
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
        """Arama adayı, okunan URL ve tabloya seçilen web kaynağını ayrı kanıt durumlarında tut."""
        def upsert(target: list[dict[str, Any]], entry: dict[str, Any]) -> None:
            url = entry.get("url")
            old = next((item for item in target if item.get("url") == url), None)
            if old is None:
                target.append(entry)
            else:
                old.update({key: value for key, value in entry.items() if value is not None})

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
                             "table_used": bool(v.get("table_used")),
                             "table_index": v.get("table_index"), "table_label": v.get("table_label"),
                             "table_rows": v.get("table_rows"), "table_columns": v.get("table_columns"),
                             "cache_reused": v.get("cache_reused"),
                             **({"extraction": v.get("extraction")} if v.get("extraction") else {}),
                             **({"ocr": v.get("ocr")} if v.get("ocr") else {})}
                    upsert(panel.web_sources, entry)
        for art in artifacts:
            if art.get("kind") == "web_search":
                # K02-T04 (A06, ADR-0075): arama sonucu dış bağlamdır; veri kaynaklarından ayrı ve "veri değil" diye kaydedilir.
                for r in art.get("results") or [{"url": u} for u in art.get("hits") or []]:
                    entry = {"url": r.get("url"), "title": r.get("title"), "query": art.get("query"), "note": "web araması — bağlam, veri değil"}
                    if entry not in panel.context_sources:
                        panel.context_sources.append(entry)
                continue
            if art.get("kind") != "web":
                continue
            used = art.get("used")
            table_used = bool(art.get("table_loaded", used))
            for v in art.get("visited", []):
                entry = {"url": v.get("url"), "sha256": v.get("sha256"), "fetched_at": v.get("fetched_at"),
                         "status": v.get("status"), "title": v.get("title"),
                         "cache_reused": bool(art.get("cache_reused")),
                         **({"extraction": v.get("extraction")} if v.get("extraction") else {}),
                         **({"ocr": v.get("ocr")} if v.get("ocr") else {})}
                if used and v.get("url") == used and table_used:
                    entry.update({"table_used": True, "table_index": art.get("table_index"),
                                  "table_label": art.get("table_label"), "table_rows": art.get("table_rows"),
                                  "table_columns": art.get("table_columns")})
                    upsert(panel.web_sources, entry)
                    panel.web_reads[:] = [read for read in panel.web_reads if read.get("url") != used]
                else:
                    entry["table_used"] = False
                    upsert(panel.web_reads, entry)
            for b in art.get("blocked", []):
                upsert(panel.web_unused, {"url": b.get("url"), "note": f"erişilemedi: {b.get('status')} / {b.get('reason')}"})
            for item in art.get("limit_exceeded", [])[:10]:
                if isinstance(item, dict):
                    upsert(panel.web_unused, {"url": item.get("url"), "note": f"boyut sınırı: {item.get('reason')}"})
            for url, reason in art.get("skipped", [])[:10]:
                upsert(panel.web_unused, {"url": url, "note": f"atlandı: {reason}"})
        selected_urls = {w.get("url") for w in panel.web_sources}
        panel.web_reads[:] = [w for w in panel.web_reads if w.get("url") not in selected_urls]
        read_urls = selected_urls | {w.get("url") for w in panel.web_reads}
        panel.context_sources[:] = [c for c in panel.context_sources if c.get("url") not in read_urls]

    # ------------------------------------------------------------------ giriş
    def _record_panel(self, panel: EvidencePanel, answer: str, record: dict[str, Any], *,
                      workspace: AnalysisWorkspace | None = None, question: str = "") -> EvidencePanel:
        """Kayıt turu (ingest_from_url / promote_draft): kanıt yazılan kayıttır.

        Sayılar araç kartıyla eşleştirilir (kart araç çıktısıdır; "11 satır", "2023" oradan gelir); aynı turda model
        kaydı sorgulayıp tablo da ürettiyse (ölçüldü: kayıttan sonra lakehouse_query) tablodaki sayılar da eşleşir.
        Dosya zinciri artifact sha256 ile: adaptör artifact izi sunuyorsa `meta.artifact`'ta aranır ve bulunmazsa
        halka kopuk sayılır; terfide zincir Silver'a kopyalanan satırlarda biter."""
        card = str(record.get("card") or "")
        card_numbers = {n for _, n in _number_texts(card)}
        panel.numbers = [NumberEvidence(number=n, text=t, matched=n in card_numbers,
                                        column="kayıt kartı" if n in card_numbers else None)
                         for t, n in _number_texts(answer)]
        table = getattr(workspace, "table", None) if workspace is not None else None
        if table is not None and not table.empty:
            try:
                from_table = self._match_numbers(answer, table, _time_column(table), previous=workspace.previous_tables(),
                                                 peeks=workspace.peeks(), question=question)
            except Exception:  # noqa: BLE001 — tablo eşlemesi kayıt panelini düşürmez
                from_table = []
            matched_in_table = {n.number for n in from_table if n.matched}
            for n in panel.numbers:
                if not n.matched and n.number in matched_in_table:
                    n.matched, n.column = True, "aynı turdaki sorgu tablosu"
        rec = {k: record.get(k) for k in ("tool", "series_id", "locator", "artifact_sha256", "run_id",
                                          "rows_written", "rows_unchanged", "rows_promoted")}
        sha = rec.get("artifact_sha256")
        if sha and isinstance(self.lakehouse, EvidenceCapable):
            try:
                found = self.lakehouse.evidence_for_artifacts([str(sha)])
            except Exception as exc:  # noqa: BLE001 — iz okunamazsa panel bunu söyler, cevabı düşürmez
                found = {}
                panel.gaps.append(f"artifact izi okunamadı: {exc}")
            panel.artifacts = dict(found)
            rec["artifact_found"] = str(sha) in found
            if not rec["artifact_found"]:
                panel.gaps.append(f"yazılan artifact {str(sha)[:12]}… meta.artifact'ta bulunamadı")
        elif not sha and rec.get("tool") != "promote_draft":
            panel.gaps.append("kayıt kartı artifact sha256 taşımıyor")
        elif rec.get("tool") == "promote_draft" and not rec.get("rows_promoted"):
            panel.gaps.append("terfi kartı Silver'a kopyalanan satır sayısı taşımıyor")
        panel.record = rec
        unmatched = [n.text for n in panel.numbers if not n.matched]
        if unmatched:
            # Aynı ön ek: sayı boşluğu "sayılar" rozetinde sayılır, dosya zincirini ✗ yapmaz (M16 ölçümü, chain_gaps).
            panel.gaps.append("tabloda bulunmayan sayılar (kayıt kartında da yok): " + ", ".join(unmatched[:8]))
        return panel

    def build(
        self, question: str, answer: str, workspace: AnalysisWorkspace, steps: list[Any],
        *, artifacts: list[dict[str, Any]] | None = None,
    ) -> EvidencePanel:
        panel = EvidencePanel(question=question, supports_artifacts=isinstance(self.lakehouse, EvidenceCapable))
        table = workspace.table
        records = [a for a in (artifacts or []) if isinstance(a, dict) and a.get("kind") == "record"]
        if records:
            # Kayıt turu her zaman kaydı anlatır: önceki turdan kalan tablo bu cevabın kanıtı değildir
            # (ölçüldü: terfi turunda panel eski sorgu tablosunun halkalarını gösteriyordu).
            return self._record_panel(panel, answer, records[-1], workspace=workspace, question=question)
        if table is None or table.empty:
            panel.gaps.append("analiz tablosu yok")
            panel.numbers = [NumberEvidence(number=n, text=t) for t, n in _number_texts(answer)]
            self._web(panel, artifacts or [], workspace)
            return panel
        panel.table_rows = len(table)
        panel.inspected_rows = min(len(table), self.max_rows)
        time_col = _time_column(table)
        active_id = getattr(workspace, "active_source_id", None)
        sources = [(s.id, s.frame, s.provenance) for s in reversed(list(workspace.sources())) if s.id != active_id] \
            if hasattr(workspace, "sources") else []
        panel.numbers = self._match_numbers(answer, table, time_col, previous=workspace.previous_tables(),
                                            peeks=workspace.peeks(), question=question, previous_sources=sources)
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
        if any(w.get("ocr") for w in panel.web_sources):
            panel.ocr_unverified = True
            panel.gaps.append("sayılar OCR ile görüntüden okundu; hücreler doğrulanmadı, kesin sonuç sayılmaz")
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
            from ..contracts.evidence import CHAIN_DIGEST_MISMATCH, CHAIN_FULL
            for state, n in panel.chain_breakdown().items():
                if state not in (CHAIN_FULL, CHAIN_DIGEST_MISMATCH):
                    panel.gaps.append(f"{n} gözlemde dosya halkası eksik: {state}")
            altered = sorted({o.artifact_sha256[:12] for o in panel.observations if o.raw_digest_ok is False})
            if altered:
                panel.gaps.append(f"{len(altered)} RAW dosyasının baytları kayıtlı özetle uyuşmuyor (dosya sonradan değişmiş): "
                                  + ", ".join(altered[:4]))
        return panel


__all__ = ["EvidenceBuilder"]
