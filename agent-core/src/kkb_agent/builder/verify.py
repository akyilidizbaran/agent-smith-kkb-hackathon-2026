"""Doğrulayıcı — öneriyi yayınlama kurallarıyla sınar, modele sormadan.

Profilci bir iddia üretir. Burası o iddiayı aynı veriye karşı, yayınlama
katmanının uygulayacağı kurallarla sınar: kolonlar var mı, tarih beyan edilen
biçimle %100 ayrışıyor mu, değer beyan edilen ayraçlarla %100 ayrışıyor mu,
hiçbir satır sessizce düşmüyor mu, aynı (tarih, entity) iki kez geçiyor mu
(yayınlamada revizyon çatışması olur), series_id `adhoc:` alanında mı ve
mevcut bir seriyle çakışıyor mu.

Sonuç bir rapordur: her kontrol adıyla, geçti/kaldı ve ayrıntısıyla. Kalan
kontrol raporu düşürür; hiçbir şey onarılmaz, hiçbir varsayım eklenmez.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd

from .profile import MappingProposal, _parse_number, parse_date


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class VerificationReport:
    checks: tuple[Check, ...]
    rows_in: int
    rows_mapped: int
    rows_null_value: int

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if not c.ok)

    def render(self) -> str:
        lines = [f"DOĞRULAMA: {'geçti' if self.ok else 'KALDI'} — {self.rows_mapped}/{self.rows_in} satır eşlendi, "
                 f"{self.rows_null_value} boş değer korundu"]
        for c in self.checks:
            lines.append(f"  {'✓' if c.ok else '✗'} {c.name}: {c.detail}")
        return "\n".join(lines)


def verify_mapping(
    frame: pd.DataFrame,
    proposal: MappingProposal,
    *,
    existing_series_ids: Iterable[str] = (),
) -> VerificationReport:
    checks: list[Check] = []
    cols = set(map(str, frame.columns))

    # 1. series_id alanı ve çakışma
    ok_ns = proposal.series_id.startswith("adhoc:") and len(proposal.series_id) > len("adhoc:")
    checks.append(Check("series_id 'adhoc:' alanında", ok_ns, proposal.series_id))
    clash = proposal.series_id in set(existing_series_ids)
    checks.append(Check("series_id mevcut bir seriyle çakışmıyor", not clash,
                        "çakışıyor — küratörlü ya da başka bir draft seri aynı adı taşıyor" if clash else "serbest"))

    # 2. kolonlar var mı
    for label, name in (("tarih kolonu", proposal.observation_date_column), ("değer kolonu", proposal.value_column)):
        checks.append(Check(f"{label} tabloda var", name in cols, name))
    if proposal.entity_id_column is not None:
        checks.append(Check("entity kolonu tabloda var", proposal.entity_id_column in cols, proposal.entity_id_column))
    if not all(c.ok for c in checks):
        return VerificationReport(tuple(checks), int(len(frame)), 0, 0)

    # 3. tarih: beyan edilen biçimle %100
    bad_dates: list[str] = []
    parsed_dates: list[object] = []
    for raw in frame[proposal.observation_date_column].tolist():
        text = "" if raw is None else str(raw).strip()
        try:
            parsed_dates.append(parse_date(text, proposal.date_format))
        except ValueError:
            bad_dates.append(text or "<boş>")
    checks.append(Check(
        f"tarihler {proposal.date_format!r} ile ayrışıyor", not bad_dates,
        f"{len(frame) - len(bad_dates)}/{len(frame)}" + (f"; ayrışmayan: {bad_dates[:3]}" if bad_dates else ""),
    ))

    # 4. değer: beyan edilen ayraçlarla %100 (boş hücre NULL olarak korunur)
    bad_vals: list[str] = []
    nulls = 0
    for raw in frame[proposal.value_column].tolist():
        text = "" if raw is None else str(raw)
        try:
            n = _parse_number(text, proposal.decimal_separator, proposal.thousands_separator)
        except ValueError:
            bad_vals.append(text)
            continue
        if n is None:
            nulls += 1
    checks.append(Check(
        f"değerler ondalık={proposal.decimal_separator!r} binlik={proposal.thousands_separator!r} ile ayrışıyor",
        not bad_vals,
        f"{len(frame) - len(bad_vals)}/{len(frame)}, {nulls} boş" + (f"; ayrışmayan: {bad_vals[:3]}" if bad_vals else ""),
    ))

    # 5. satır sayısı korunuyor mu — sessiz düşme yok
    mapped = len(frame) - len(bad_dates) - len(bad_vals)
    checks.append(Check("hiçbir satır sessizce düşmüyor", mapped == len(frame), f"{mapped}/{len(frame)}"))

    # 6. (tarih, entity) tekilliği — yayınlamada aynı gözlemin iki değeri revizyon çatışmasıdır
    if not bad_dates:
        ents = (frame[proposal.entity_id_column].tolist() if proposal.entity_id_column else [None] * len(frame))
        keys = Counter((d, ("" if e is None else str(e).strip())) for d, e in zip(parsed_dates, ents))
        dups = [k for k, n in keys.items() if n > 1]
        checks.append(Check(
            "aynı (tarih, entity) yalnız bir kez geçiyor", not dups,
            "tekil" if not dups else f"{len(dups)} tekrar, ör. {dups[0][0]}" + (f" / {dups[0][1]}" if dups[0][1] else "")
            + ("; entity kolonu eksik olabilir" if proposal.entity_id_column is None else ""),
        ))

    # 7. belirsiz öneri yayınlanmaz
    amb = proposal.ambiguous
    checks.append(Check("öneride belirsiz alan yok", not amb,
                        "yok" if not amb else f"kullanıcıya sorulmalı: {', '.join(amb)}"))

    return VerificationReport(tuple(checks), int(len(frame)), int(mapped), int(nulls))


__all__ = ["Check", "VerificationReport", "verify_mapping"]
