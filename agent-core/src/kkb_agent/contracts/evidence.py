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


# Boşluk metinleri core/evidence.py'de üretilir; rozet ayrımı bu iki imle yapılır (metin değişirse test düşer).
_CLAIM_GAP_PREFIX = "tabloda bulunmayan sayılar"
_PROVENANCE_GAP_MARK = "kolonunun provenance kaydı yok"
_OCR_GAP_PREFIX = "sayılar OCR ile görüntüden okundu"


@dataclass(frozen=True)
class ObservationEvidence:
    """Bir Silver/adhoc gözleminin kaynak baytlarına kadar izi.

    D06 (ADR-0070): yol METNİ ile dosyanın DURUMU ayrıdır. Yollar kayıttan gelir; varlık ve okunabilirlik her okumada
    diskten canlı bakılır (sonradan silinen dosya yeşil kalmaz); RAW özeti kurulum anında denetlenir ve `checked_at`
    ile taşınır. Tam fiziksel zincir: RAW var + okunur + sha256 kayıtla aynı + Bronze var.
    """

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
    raw_path: str | None       # RAW: içerik adresli ham dosya (kayıttaki/çözülen yol metni)
    bronze_path: str | None    # Bronze parquet yolu (adaptörün bulduğu)
    relation: str = "silver.fact_observation"
    # A23 (M16): RAW içerik adreslidir; dosya baytlarının sha256'sı kayıttaki özetle aynı mı? None = denetlenmedi/dosya yok.
    raw_digest_ok: bool | None = None
    checked_at: datetime | None = None   # RAW özeti ne zaman denetlendi (D06-T02)

    @property
    def complete(self) -> bool:
        """Kayıt zinciri: sha + kaynak adresi + çekim zamanı. Fiziksel dosya ayrı (`chain_state`)."""
        return bool(self.artifact_sha256 and self.locator and self.fetched_at)

    @property
    def raw_present(self) -> bool:
        """RAW dosyası ŞU AN diskte ve okunabilir mi (canlı)."""
        import os
        from pathlib import Path
        return bool(self.raw_path) and Path(self.raw_path).is_file() and os.access(self.raw_path, os.R_OK)

    @property
    def bronze_present(self) -> bool:
        from pathlib import Path
        return bool(self.bronze_path) and Path(self.bronze_path).is_file()

    @property
    def chain_state(self) -> str:
        """Fiziksel halka durumu (D06-T03): tam | ham kaynak eksik | işlenmiş dosya eksik | özet uyuşmuyor |
        özet denetlenmedi | dosya yok. Kayıt (metadata) eksikliği `complete` ile ayrıca söylenir."""
        raw, bronze = self.raw_present, self.bronze_present
        if raw and self.raw_digest_ok is False:
            return CHAIN_DIGEST_MISMATCH
        if not raw and not bronze:
            return CHAIN_NO_FILES
        if not raw:
            return CHAIN_RAW_MISSING
        if self.raw_digest_ok is not True:
            return CHAIN_UNCHECKED
        return CHAIN_FULL if bronze else CHAIN_BRONZE_MISSING

    @property
    def file_present(self) -> bool:
        """Tam fiziksel kanıt (M13-T09, D06): RAW doğrulanmış ve Bronze mevcut. Yalnız Bronze kalmışsa tam değildir."""
        return self.chain_state == CHAIN_FULL


CHAIN_FULL = "tam"
CHAIN_RAW_MISSING = "ham kaynak (RAW) eksik, işlenmiş veri (Bronze) var"
CHAIN_BRONZE_MISSING = "ham kaynak var, işlenmiş dosya (Bronze) eksik"
CHAIN_DIGEST_MISMATCH = "RAW baytları kayıtlı özetle uyuşmuyor"
CHAIN_UNCHECKED = "RAW var ama özeti denetlenmedi"
CHAIN_NO_FILES = "RAW ve Bronze dosyası yok"


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
    sign_warning: bool = False      # büyüklük tabloda var ama işaret ters ve metinde yön sözcüğü yok
    from_question: bool = False     # sayı soruda geçiyor; tabloda yoksa doğrulanmamış iddia
    period_warning: bool = False    # K02-T14: cevap sayının yanında bir dönem yazıyor ama sayı tabloda BAŞKA dönemde


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
    web_sources: list[dict[str, Any]] = field(default_factory=list)   # kullanılan sayfa: url, sha256, fetched_at
    web_unused: list[dict[str, Any]] = field(default_factory=list)    # taranıp kullanılmayan / erişilemeyen
    inspected_rows: int = 0         # kaç satır incelendi (ilk N); tablo daha büyükse kapsam notu
    ocr_unverified: bool = False    # K02-T06 (A12): sayılar OCR ile görüntüden okunmuş bir tablodan; kesin sonuç sayılmaz

    @property
    def matched_numbers(self) -> int:
        return sum(1 for n in self.numbers if n.matched)

    # Üç ayrı durum (M13-T08, ADR-0050): tek yeşil rozet hepsinin yerine geçmez.
    @property
    def claims_ok(self) -> bool:
        """Cevaptaki her sayı bir araç çıktısında, doğru işaretle; sorudan kopya doğrulanmamış sayı yok."""
        if self.ocr_unverified and self.numbers:
            return False             # tabloda eşleşse de tablo OCR tahmini: sayı doğrulanmış sayılmaz
        return all(n.matched and not n.sign_warning and not n.period_warning for n in self.numbers)

    @property
    def provenance_ok(self) -> bool:
        """Her kolonun sorgu izi var (türetilmiş kolon dâhil)."""
        return not any(c.sql is None for c in self.columns)

    @property
    def chain_gaps(self) -> list[str]:
        """Yalnız zincir halkalarının boşlukları. Sayı ve sorgu izi boşlukları kendi rozetlerinde sayılır;
        M16 ölçümü (14 Eyl): tek eşleşmeyen sayı, dosyaları diskte duran zinciri de ✗ gösteriyordu."""
        return [g for g in self.gaps if not g.startswith((_CLAIM_GAP_PREFIX, _OCR_GAP_PREFIX)) and _PROVENANCE_GAP_MARK not in g]

    @property
    def chain_ok(self) -> bool:
        """Kaynak zinciri: gözlem → artifact → RAW/Bronze dosyası diskte; ya da web sayfası sha256+zaman."""
        gaps = self.chain_gaps
        chained = [c for c in self.columns if not (c.sql or "").startswith("türetilmiş:")]
        if self.columns and not chained:
            return not gaps             # tablo yalnız türetilmiş kolonlardan oluşuyor (olağan dışı)
        if self.web_sources and not self.observations:
            return not gaps               # zincir web sayfasının baytlarında biter: URL + sha256 + zaman
        if self.supports_artifacts:
            if not self.observations or not all(o.complete and o.chain_state == CHAIN_FULL for o in self.observations):
                return False
        return not gaps

    def chain_breakdown(self) -> dict[str, int]:
        """Gözlemlerin fiziksel halka durumlarının sayımı (canlı)."""
        out: dict[str, int] = {}
        for o in self.observations:
            out[o.chain_state] = out.get(o.chain_state, 0) + 1
        return out

    @property
    def complete(self) -> bool:
        """Üçü birden: iddialar, sorgu izi, dosya zinciri."""
        return self.claims_ok and self.provenance_ok and self.chain_ok

    def states(self) -> dict[str, bool]:
        return {"sayılar": self.claims_ok, "sorgu izi": self.provenance_ok, "dosya zinciri": self.chain_ok}

    def summary(self) -> str:
        arts = len(self.artifacts)
        fetched = sorted({str(a.get("fetched_at"))[:10] for a in self.artifacts.values() if a.get("fetched_at")})
        state = "tam" if self.complete else "EKSİK"
        parts = [
            f"{self.matched_numbers}/{len(self.numbers)} sayı tabloda"
            + (f" ({sum(1 for n in self.numbers if n.sign_warning)} işaret uyarısı)" if any(n.sign_warning for n in self.numbers) else "")
            + (f" ({sum(1 for n in self.numbers if n.period_warning)} dönem uyuşmazlığı)" if any(n.period_warning for n in self.numbers) else "")
            + (f" ({sum(1 for n in self.numbers if n.from_question and not n.matched)} sorudan, doğrulanmadı)"
               if any(n.from_question and not n.matched for n in self.numbers) else ""),
            f"{len(self.columns)} kolon → SQL",
        ]
        if not self.claims_ok or not self.provenance_ok or not self.chain_ok:
            parts.append("durum: " + " · ".join(f"{k} {'✓' if v else '✗'}" for k, v in self.states().items()))
        if self.inspected_rows and self.table_rows > self.inspected_rows:
            parts.append(f"ilk {self.inspected_rows}/{self.table_rows} satır incelendi")
        if self.web_sources:
            parts.append(f"{len(self.web_sources)} web sayfası (sha256+zaman)")
        else:
            parts.append(f"{len(self.observations)} gözlem → {arts} artifact")
            breakdown = self.chain_breakdown()
            if self.observations and set(breakdown) != {CHAIN_FULL}:
                parts.append("dosya halkaları: " + ", ".join(f"{n} {k}" for k, n in breakdown.items()))
        if fetched:
            parts.append(f"çekim {', '.join(fetched)}")
        return f"kanıt zinciri {state}: " + " · ".join(parts)

    def render(self, *, max_observations: int = 12) -> str:
        lines = [self.summary(), ""]
        lines.append("SAYILAR (cevap → tablo):")
        for n in self.numbers[:30]:
            if n.matched:
                where = f" (satır {n.row_index})" if n.row_index is not None else ""
                warn = ("  ⚠ tabloda ters işaret" if n.sign_warning else "") + ("  ⚠ tabloda başka dönemde" if n.period_warning else "")
                lines.append(f"  {n.text:>14}  → {n.column} @ {n.row_key}{where}{warn}")
            else:
                lines.append(f"  {n.text:>14}  → " + ("SORUDAN, TABLODA YOK (doğrulanmamış iddia)" if n.from_question else "TABLODA YOK"))
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
                lines.append(f"      RAW: {o.raw_path}" + ("" if o.raw_present else "  (YOK)"))
            if o.bronze_path:
                lines.append(f"      Bronze: {o.bronze_path}" + ("" if o.bronze_present else "  (YOK)"))
            lines.append(f"      dosya halkası: {o.chain_state}"
                         + (f" · özet denetimi {o.checked_at:%Y-%m-%d %H:%M}" if o.checked_at else ""))
        if len(self.observations) > max_observations:
            lines.append(f"  … {len(self.observations) - max_observations} gözlem daha")
        if not self.observations:
            lines.append("  (gözlem izi yok)")
        if self.web_sources:
            lines.append("")
            lines.append("WEB KAYNAĞI (kullanılan sayfa):")
            for w in self.web_sources:
                lines.append(f"  {w.get('url')} | sha256 {str(w.get('sha256'))[:12]}… | çekim {w.get('fetched_at')} | HTTP {w.get('status')}")
        if self.web_unused:
            lines.append("")
            lines.append("TARANDI, KULLANILMADI / ERİŞİLEMEDİ:")
            for w in self.web_unused:
                lines.append(f"  {w.get('url')} — {w.get('note')}")
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
                 "fetched_at": o.fetched_at.isoformat() if o.fetched_at else None,
                 "checked_at": o.checked_at.isoformat() if o.checked_at else None,
                 "raw_present": o.raw_present, "bronze_present": o.bronze_present, "chain_state": o.chain_state}
                for o in self.observations
            ],
            "chain_breakdown": self.chain_breakdown(),
            "artifacts": {k: {kk: (vv.isoformat() if isinstance(vv, datetime) else vv) for kk, vv in v.items()}
                          for k, v in self.artifacts.items()},
            "consulted_unused": self.consulted_unused,
            "gaps": self.gaps,
            "ocr_unverified": self.ocr_unverified,
            "supports_artifacts": self.supports_artifacts,
            "chart_paths": self.chart_paths,
            "web_sources": self.web_sources,
            "web_unused": self.web_unused,
        }


__all__ = ["CHAIN_BRONZE_MISSING", "CHAIN_DIGEST_MISMATCH", "CHAIN_FULL", "CHAIN_NO_FILES", "CHAIN_RAW_MISSING", "CHAIN_UNCHECKED",
           "ColumnEvidence", "EvidenceCapable", "EvidencePanel", "NumberEvidence", "ObservationEvidence"]
