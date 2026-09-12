"""Kanıt zinciri sözleşmesi — cevaptaki sayıdan kaynak baytlarına (ADR-0033).

"Bu rakam nereden geliyor?" sorusunun cevabı bir cümle değil, bir zincirdir:

    cevaptaki sayı → tablo hücresi → SQL (provenance) → Silver satırı
      → artifact_sha256 → Bronze parquet → RAW dosyası → kaynak URL + fetched_at

Zincirin her halkası ayrı bir katmandan gelir: sayı eşlemesi anlatı doğrulamadan
(grounding), hücre → SQL workspace provenance'ından, satır → artifact adaptörden
(`EvidenceCapable`), dosya yolları diskten. Hiçbir halka tahmin edilmez; halka yoksa
zincir "eksik" der ve neresinin eksik olduğunu söyler (seed adaptöründe artifact yoktur).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ObservationEvidence:
    """Bir Silver/adhoc gözleminin kaynak baytlarına kadar izi."""

    series_id: str
    entity_id: str | None
    observation_date: date
    value: float | None
    quality_flag: str
    artifact_sha256: str
    vintage_id: str | None
    run_id: str | None
    fetched_at: datetime | None
    locator: str | None        # kaynak URL ya da dosya
    http_status: int | None
    raw_path: str | None       # RAW: içerik adresli ham dosya
    bronze_path: str | None    # Bronze parquet; diskte bulunamadıysa None
    relation: str = "silver.fact_observation"

    @property
    def complete(self) -> bool:
        return bool(self.artifact_sha256 and self.locator and self.fetched_at)


@runtime_checkable
class EvidenceCapable(Protocol):
    """Gözlemden artifact'e inebilen lakehouse'lar. Seed adaptörü sunmaz; zincir SQL'de biter."""

    def evidence_for_observations(
        self, series_id: str, observation_dates: list[date], *, entity_id: str | None = None
    ) -> list[ObservationEvidence]:
        """Verilen tarihlerdeki gözlemlerin izi. Tarihi olmayan gözlem listede yer almaz."""
        ...

    def evidence_for_artifacts(self, artifact_sha256s: list[str]) -> dict[str, dict[str, Any]]:
        """sha → {locator, fetched_at, http_status, raw_path, bronze_path, source_id, dataset_id}."""
        ...


@dataclass
class NumberEvidence:
    """Cevaptaki bir sayının tabloda nereye düştüğü."""

    number: float
    text: str
    column: str | None = None
    row_index: int | None = None
    row_key: str | None = None      # satırın dönem/anahtar değeri
    matched: bool = False


@dataclass
class ColumnEvidence:
    column: str
    sql: str | None
    dataset_ids: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    executed_at: datetime | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class EvidencePanel:
    """Bir cevabın kanıt paneli: sayılar, kolonlar, gözlemler, danışılıp kullanılmayanlar."""

    question: str
    numbers: list[NumberEvidence] = field(default_factory=list)
    columns: list[ColumnEvidence] = field(default_factory=list)
    observations: list[ObservationEvidence] = field(default_factory=list)
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    consulted_unused: list[str] = field(default_factory=list)   # describe edilip tabloya girmeyen
    gaps: list[str] = field(default_factory=list)                # zincirin kopuk halkaları
    supports_artifacts: bool = False
    table_rows: int = 0
    chart_paths: list[str] = field(default_factory=list)

    @property
    def matched_numbers(self) -> int:
        return sum(1 for n in self.numbers if n.matched)

    @property
    def complete(self) -> bool:
        """Zincir tam: her sayı bir hücrede, her kolonun SQL'i var, artifact destekleniyorsa
        her gözlem locator + fetched_at taşıyor."""
        if self.numbers and self.matched_numbers < len(self.numbers):
            return False
        if any(c.sql is None for c in self.columns):
            return False
        if self.supports_artifacts and (not self.observations or not all(o.complete for o in self.observations)):
            return False
        return not self.gaps

    def summary(self) -> str:
        arts = len(self.artifacts)
        fetched = sorted({str(a.get("fetched_at"))[:10] for a in self.artifacts.values() if a.get("fetched_at")})
        state = "tam" if self.complete else "EKSİK"
        parts = [
            f"{self.matched_numbers}/{len(self.numbers)} sayı tabloda",
            f"{len(self.columns)} kolon → SQL",
            f"{len(self.observations)} gözlem → {arts} artifact",
        ]
        if fetched:
            parts.append(f"çekiliş {', '.join(fetched)}")
        return f"kanıt zinciri {state}: " + " · ".join(parts)

    def render(self, *, max_observations: int = 12) -> str:
        lines = [self.summary(), ""]
        lines.append("SAYILAR (cevap → tablo):")
        for n in self.numbers[:30]:
            if n.matched:
                where = f" (satır {n.row_index})" if n.row_index is not None else ""
                lines.append(f"  {n.text:>14}  → {n.column} @ {n.row_key}{where}")
            else:
                lines.append(f"  {n.text:>14}  → TABLODA YOK")
        if not self.numbers:
            lines.append("  (cevapta sayı yok)")
        lines.append("")
        lines.append("KOLONLAR (tablo → SQL):")
        for c in self.columns:
            src = ", ".join(c.sources) or "—"
            lines.append(f"  {c.column}: {src}")
            if c.sql:
                sql = " ".join(c.sql.split())
                lines.append(f"      SQL: {sql[:220]}{'…' if len(sql) > 220 else ''}")
            for w in c.warnings[:3]:
                lines.append(f"      uyarı: {w[:160]}")
        lines.append("")
        lines.append("GÖZLEMLER (satır → artifact → RAW):")
        for o in self.observations[:max_observations]:
            art = self.artifacts.get(o.artifact_sha256, {})
            when = o.fetched_at.strftime("%Y-%m-%d %H:%M") if o.fetched_at else "?"
            lines.append(
                f"  {o.series_id} @ {o.observation_date}"
                + (f" [{o.entity_id}]" if o.entity_id else "")
                + f" = {o.value} ({o.quality_flag})"
            )
            lines.append(f"      artifact {o.artifact_sha256[:12]}… çekildi {when}"
                         + (f" HTTP {o.http_status}" if o.http_status else ""))
            if o.locator:
                lines.append(f"      kaynak: {o.locator}")
            if o.raw_path:
                lines.append(f"      RAW: {o.raw_path}")
            if o.bronze_path:
                lines.append(f"      Bronze: {o.bronze_path}")
        if len(self.observations) > max_observations:
            lines.append(f"  … {len(self.observations) - max_observations} gözlem daha")
        if not self.observations:
            lines.append("  (gözlem izi yok)")
        if self.consulted_unused:
            lines.append("")
            lines.append("DANIŞILDI, KULLANILMADI: " + ", ".join(self.consulted_unused))
        if self.chart_paths:
            lines.append("")
            lines.append("GRAFİK: " + "; ".join(self.chart_paths))
        if self.gaps:
            lines.append("")
            lines.append("EKSİK HALKALAR:")
            lines += [f"  - {g}" for g in self.gaps]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "complete": self.complete,
            "summary": self.summary(),
            "numbers": [n.__dict__ for n in self.numbers],
            "columns": [{**c.__dict__, "executed_at": c.executed_at.isoformat() if c.executed_at else None} for c in self.columns],
            "observations": [
                {**o.__dict__, "observation_date": o.observation_date.isoformat(),
                 "fetched_at": o.fetched_at.isoformat() if o.fetched_at else None}
                for o in self.observations
            ],
            "artifacts": {k: {kk: (vv.isoformat() if isinstance(vv, datetime) else vv) for kk, vv in v.items()}
                          for k, v in self.artifacts.items()},
            "consulted_unused": self.consulted_unused,
            "gaps": self.gaps,
            "supports_artifacts": self.supports_artifacts,
            "chart_paths": self.chart_paths,
        }


__all__ = ["ColumnEvidence", "EvidenceCapable", "EvidencePanel", "NumberEvidence", "ObservationEvidence"]
