"""Arama defteri — katalog aramasını çağrı sayısıyla değil, ne ürettiğiyle durdurmak (22 Eylül)

Ölçülen boşluk: benchmark P05/R02'de model 4–7 kez arama yaptı; sabit bütçe ("N arama yapıldı, durduruldu")
ya da art arda boş sonuç sayısı, "veri yok" ya da "iş tamamlanamadı" demek olmamalı. Bir aramanın değeri, YENİ
ve TEKİL aday üretip üretmediği ve istenen yüzlerin (frekans, il, kaynak) bulunup bulunmadığıdır.

Defter tur içinde tutulur:
  - her arama: sorgu, dönen kimlikler; tekil aday havuzu birikir (kimlik → ad, kaynak, frekans, birim, ölçüm, kapsam, il)
  - doygunluk: arka arkaya iki arama yeni aday üretmediyse (en az üç aramadan sonra) arama DOYMUŞtur;
    araç bunu kod olarak söyler (SEARCH_SATURATED) ve tam aday listesini verir — "veri yok" demez
  - yüzler: soru haftalık/il/kaynak istiyorsa, adaylar arasında o yüzü taşıyan var mı; yoksa mesaj bunu söyler
    ("istenen frekansta (haftalık) aday yok; bulunanlar: aylık ×3") — dürüst kapanışın girdisi
  - büyük sonuç: adaylar tablo olarak (`candidates_frame`) sunulur; modelin kısa anlatısı tam listenin yerine geçmez

Soruya özel kural yok; yüzler `core/facets.py`'den, alanlar katalog sözleşmesinden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .facets import Facets, extract_facets, province_of

CANDIDATE_COLUMNS = ("series_id", "name", "source", "frequency", "unit", "measure_type", "coverage_start", "coverage_end", "province")


def _spec_row(spec: Any) -> dict[str, Any]:
    freq = getattr(getattr(spec, "frequency", None), "value", getattr(spec, "frequency", None))
    cov = getattr(spec, "coverage", None)
    unit = None
    for col in getattr(spec, "columns", ()) or ():
        role = getattr(getattr(col, "role", None), "value", getattr(col, "role", None))
        if str(role) in ("value", "ColumnRole.VALUE") and getattr(col, "unit", None):
            unit = col.unit
            break
    return {
        "series_id": str(getattr(spec, "dataset_id", "")),
        "name": str(getattr(spec, "name", ""))[:120],
        "source": str(getattr(spec, "source", "") or ""),
        "frequency": str(freq or ""),
        "unit": unit or getattr(spec, "unit", None) or "",
        "measure_type": str(getattr(spec, "measure_type", "") or ""),
        "coverage_start": str(getattr(cov, "start", "") or ""),
        "coverage_end": str(getattr(cov, "end", "") or ""),
        "province": province_of(f"{getattr(spec, 'dataset_id', '')} {getattr(spec, 'name', '')}") or "",
    }


@dataclass
class SearchVerdict:
    new_ids: list[str]
    total_unique: int
    searches: int
    saturated: bool
    facet_note: str = ""

    def line(self) -> str:
        head = f"ARAMA DEFTERİ: {self.searches}. arama, bu aramada {len(self.new_ids)} yeni aday, toplam {self.total_unique} tekil aday"
        return head + (f"; {self.facet_note}" if self.facet_note else "")


@dataclass
class SearchLedger:
    """Tur içi arama defteri; `begin_turn` sıfırlar."""

    facets: Facets = field(default_factory=Facets)
    candidates: dict[str, dict[str, Any]] = field(default_factory=dict)
    queries: list[str] = field(default_factory=list)
    new_counts: list[int] = field(default_factory=list)
    #: Doygunluk: en az bu kadar aramadan sonra, son bu kadar arama yeni aday üretmediyse.
    MIN_SEARCHES: int = 3
    STALL_RUN: int = 2

    def begin_turn(self, question: str = "") -> None:
        self.facets = extract_facets(question or "")
        self.candidates.clear()
        self.queries.clear()
        self.new_counts.clear()

    @property
    def searches(self) -> int:
        return len(self.queries)

    @property
    def saturated(self) -> bool:
        return (self.searches >= self.MIN_SEARCHES
                and len(self.new_counts) >= self.STALL_RUN
                and all(n == 0 for n in self.new_counts[-self.STALL_RUN:]))

    def record(self, query: str, specs: list[Any]) -> SearchVerdict:
        new_ids: list[str] = []
        for spec in specs:
            row = _spec_row(spec)
            sid = row["series_id"]
            if sid and sid not in self.candidates:
                self.candidates[sid] = row
                new_ids.append(sid)
        self.queries.append(query)
        self.new_counts.append(len(new_ids))
        return SearchVerdict(new_ids=new_ids, total_unique=len(self.candidates), searches=self.searches,
                             saturated=self.saturated, facet_note=self.facet_note())

    # ---- yüzler: istenen bulundu mu?
    def facet_note(self) -> str:
        notes = []
        if self.facets.frequency:
            have = [r for r in self.candidates.values() if r["frequency"] == self.facets.frequency]
            if self.candidates and not have:
                freqs = {}
                for r in self.candidates.values():
                    freqs[r["frequency"] or "?"] = freqs.get(r["frequency"] or "?", 0) + 1
                notes.append(f"istenen frekansta ({self.facets.frequency}) aday yok; bulunanlar: "
                             + ", ".join(f"{k} ×{v}" for k, v in sorted(freqs.items())))
        if self.facets.provinces:
            have = {r["province"] for r in self.candidates.values() if r["province"]}
            missing = [p for p in self.facets.provinces if p not in have]
            if self.candidates and missing:
                notes.append("istenen il(ler) için aday yok: " + ", ".join(missing))
        if self.facets.sources:
            have = {r["source"] for r in self.candidates.values()}
            missing = [s for s in self.facets.sources if not any(s in h for h in have)]
            if self.candidates and missing:
                notes.append("istenen kaynak için aday yok: " + ", ".join(missing))
        return "; ".join(notes)

    def candidates_frame(self) -> pd.DataFrame:
        return pd.DataFrame(list(self.candidates.values()), columns=list(CANDIDATE_COLUMNS))

    def summary(self) -> dict[str, Any]:
        return {"searches": self.searches, "unique_candidates": len(self.candidates), "saturated": self.saturated,
                "facet_note": self.facet_note(), "queries": list(self.queries)}


__all__ = ["CANDIDATE_COLUMNS", "SearchLedger", "SearchVerdict"]
