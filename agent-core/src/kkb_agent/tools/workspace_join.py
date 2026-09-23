"""`workspace_join` — oturumdaki iki tabloyu anahtarla birleştirir (M11-T03, A09, ADR-0059; D01/D07, ADR-0065).

Kural: birleştirme DURUM üzerinden denetlenir, model sonucu tahmin etmez.
- Anahtar verilmediyse ve iki tabloda tek ortak kolon yoksa araç sorar (netleştirme): ortak kolonları listeler.
- Anahtar eşdeğerliği AÇIK kuraldır (`key_policy`). Varsayılan `tam`: tamsayı kimlikler Python tamsayısı olarak
  kayıpsız (float64 yok), metin olduğu gibi (baştaki sıfır, boşluk, büyük/küçük harf korunur), zaman damgası saatiyle.
  İki tarafın tipi farklıysa ya da başka bir kural sonucu değiştiriyorsa araç birleştirmez, seçenekleri sayılarıyla sorar.
- Boş anahtar hiçbir satırla eşleşmez; sayısı karta yazılır.
- Sağ tabloda (kural uygulandıktan sonra) yinelenen anahtar satırı çoğaltır: reddedilir, yinelenen değerler gösterilir.
- Eşleşmeyen satırlar iki yönde sayılır; `left` birleştirmede sol tablonun satır sayısı değişmez.
- Yardımcı kolon kullanılmaz: kullanıcının `__k`, `_merge` gibi kolonları ezilemez. Ad çakışması `<kolon>_<kN>` ile, o da
  doluysa sayı sonekiyle çözülür; her kolon kendi kaynağının provenance'ını ve kullanılan anahtar kuralını taşır.
Veri havuzuna yazmaz; kaynak tablolar değişmez, sonuç yeni aktif tablo olur.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from ..core.errors import ToolError
from ..core.tool import Tool, ToolResult
from ..core.workspace import AnalysisWorkspace

KeyPolicy = Literal["tam", "metin", "metin_normal", "sayi", "tarih_gun", "ay"]

POLICY_TEXT: dict[str, str] = {
    "tam": "tam eşitlik (tamsayı kayıpsız, metin olduğu gibi, zaman damgası saatiyle)",
    "metin": "iki taraf metin olarak birebir (1 = '1', '001' ≠ '1')",
    "metin_normal": "baş/son boşluk ve büyük/küçük harf farkı yok sayıldı (Türkçe İ/ı dahil)",
    "sayi": "tamsayı olarak (baştaki sıfırlar yok sayıldı: '001' = 1)",
    "tarih_gun": "gün düzeyinde tarih (saat atıldı)",
    "ay": "ay düzeyinde (202101, 2021-01, 2021-01-31 aynı ay; YYYY-MM)",
}
_INT_EXACT_LIMIT = 2 ** 53          # float64'ün her tamsayıyı kayıpsız taşıdığı sınır
# Tip çifti (alfabetik) → sonucu değiştirebilecek açık kurallar. Aynı tipte yalnız metin için gevşek kurallar sınanır.
_ALTERNATIVES = {"metin": ("metin_normal", "sayi"), "metin|tamsayı": ("metin", "sayi"), "ondalık|tamsayı": ("sayi",),
                 "tarih|zaman": ("tarih_gun",), "metin|tarih": ("tarih_gun",), "metin|zaman": ("tarih_gun",)}
# "ay" kuralı önerilmez: gün düzeyindeki tarihleri aya indirmek farklı günleri birleştirir. Yalnız kullanıcı aylık
# birleştirme istediğinde açıkça seçilir (key_policy='ay').


class JoinParams(BaseModel):
    right: str = Field(description="Eklenecek oturum tablosunun kimliği (k1, k2, …)")
    left: str = Field(default="aktif", description="Sol tablo: 'aktif' ya da kN")
    left_key: str | None = Field(default=None, description="Sol tablodaki eşleştirme kolonu; boşsa tek ortak kolon kullanılır")
    right_key: str | None = Field(default=None, description="Sağ tablodaki eşleştirme kolonu; boşsa left_key ile aynı ad")
    how: Literal["left", "inner", "outer"] = Field(default="left", description="left: sol tablonun satırları korunur")
    columns: list[str] | None = Field(default=None, description="Sağ tablodan alınacak kolonlar; boşsa anahtar dışındakilerin hepsi")
    key_policy: KeyPolicy = Field(
        default="tam",
        description=("Anahtar eşleme kuralı. tam (varsayılan): birebir. metin: iki taraf metin olarak birebir. "
                     "metin_normal: boşluk ve büyük/küçük harf farkı yok sayılır. sayi: tamsayı olarak, baştaki sıfırlar "
                     "yok sayılır. tarih_gun: saat atılır. ay: 202101 / 2021-01 / 2021-01-31 aynı ay. Kullanıcı 'aylık "
                     "tarih bazında birleştir/hizala' dediyse tarih anahtarlarında 'ay' kuralını doğrudan kullan; diğer "
                     "'tam' dışı kuralları YALNIZ araç sorduktan sonra kullanıcı o eşdeğerliği kabul ettiyse seç."))
    purpose: str = Field(description="Bu birleştirmenin neyi cevapladığını anlatan tek cümle")


class KeyError_(Exception):
    """Anahtar bu kuralla güvenle çevrilemiyor (hassasiyet kaybı, çevrilemeyen değer)."""


def _is_missing(x: Any) -> bool:
    if x is None or x is pd.NA or x is pd.NaT:
        return True
    try:
        return bool(pd.isna(x)) if not isinstance(x, (str, bytes)) else False
    except (TypeError, ValueError):
        return False


def _tr_fold(text: str) -> str:
    t = text.replace("İ", "i").replace("I", "ı").lower().replace("ı", "i").replace("i\u0307", "i")
    return re.sub(r"\s+", " ", t.casefold()).strip()


def key_kind(s: pd.Series) -> str:
    """tamsayı | ondalık | metin | tarih | zaman (boş değerler hariç). Kaynak tipine bakar, değeri dönüştürmez."""
    v = s[[not _is_missing(x) for x in s.tolist()]]
    if pd.api.types.is_bool_dtype(s):
        return "metin"
    if pd.api.types.is_datetime64_any_dtype(s) or (len(v) and all(isinstance(x, (pd.Timestamp,)) or
                                                           (hasattr(x, "year") and hasattr(x, "month") and not isinstance(x, str))
                                                           for x in v.tolist())):
        ts = pd.to_datetime(v)
        return "tarih" if len(ts) == 0 or bool((ts == ts.dt.normalize()).all()) else "zaman"
    if pd.api.types.is_integer_dtype(s):
        return "tamsayı"
    if pd.api.types.is_float_dtype(s):
        arr = v.to_numpy(dtype=float)
        return "tamsayı" if len(arr) and bool(np.all(np.floor(arr) == arr)) else ("ondalık" if len(arr) else "tamsayı")
    if len(v) and all(isinstance(x, (int, np.integer)) and not isinstance(x, (bool, np.bool_)) for x in v.tolist()):
        return "tamsayı"
    return "metin"


def _to_int(x: Any) -> int:
    if isinstance(x, (bool, np.bool_)):
        raise KeyError_(f"mantıksal değer tamsayı kimliği değildir: {x!r}")
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        if not float(x).is_integer():
            raise KeyError_(f"ondalık değer tamsayı kimliğine çevrilemez: {x!r}")
        if abs(float(x)) >= _INT_EXACT_LIMIT:
            raise KeyError_(f"kimlik ondalık sayı olarak okunmuş ve 2^53'ü aşıyor ({x!r}); hassasiyet kaynakta kaybolmuş olabilir")
        return int(x)
    text = str(x).strip()
    if not re.fullmatch(r"[+-]?\d+", text):
        raise KeyError_(f"tamsayıya çevrilemeyen anahtar: {x!r}")
    return int(text)


def key_values(s: pd.Series, policy: str, kind: str) -> list[Any]:
    """Kurala göre karşılaştırma değerleri (hashable); boş → None. Ham değerler değişmez."""
    out: list[Any] = []
    for x in s.tolist():
        if _is_missing(x):
            out.append(None)
            continue
        if policy == "tam":
            if kind == "tamsayı":
                out.append(_to_int(x))
            elif kind == "ondalık":
                out.append(float(x))
            elif kind in ("tarih", "zaman"):
                out.append(pd.Timestamp(x))
            else:
                out.append(x if isinstance(x, str) else str(x))
        elif policy == "metin":
            if isinstance(x, (float, np.floating)) or isinstance(x, (int, np.integer)):
                out.append(str(_to_int(x)) if not isinstance(x, (float, np.floating)) or float(x).is_integer() else str(x))
            else:
                out.append(str(x))
        elif policy == "metin_normal":
            out.append(_tr_fold(str(_to_int(x)) if isinstance(x, (int, np.integer, float, np.floating)) and kind == "tamsayı" else str(x)))
        elif policy == "sayi":
            out.append(_to_int(x))
        elif policy == "tarih_gun":
            try:
                out.append(pd.Timestamp(x).date())
            except (ValueError, TypeError) as exc:
                raise KeyError_(f"tarihe çevrilemeyen anahtar: {x!r}") from exc
        elif policy == "ay":
            from ..builder.temporal import canonical_month
            month = canonical_month(x)
            if month is None:
                raise KeyError_(f"aya çevrilemeyen anahtar: {x!r}")
            out.append(month)
        else:  # pragma: no cover — şema dışı
            raise KeyError_(f"bilinmeyen anahtar kuralı: {policy}")
    return out


def _match_count(lkeys: list[Any], rkeys: list[Any]) -> int:
    rset = {k for k in rkeys if k is not None}
    return sum(1 for k in lkeys if k is not None and k in rset)


class WorkspaceJoinTool(Tool):
    name = "workspace_join"
    role = "execute"
    description = (
        "Oturumdaki iki tabloyu (aktif tablo ve kN) anahtar kolonla birleştirir; sonuç yeni aktif tablo olur. "
        "Anahtarlar varsayılan olarak BİREBİR eşlenir (key_policy='tam'); tip farkı ya da boşluk/harf/baştaki sıfır farkı "
        "sonucu değiştiriyorsa araç birleştirmez ve seçenekleri sayılarıyla döner: kullanıcıya sor, kabul ettiği kuralla "
        "yeniden çağır. Yinelenen anahtar, boş anahtar, eşleşmeyen satır ve kolon adı çakışması karta yazılır."
    )
    Params = JoinParams

    def __init__(self, workspace: AnalysisWorkspace) -> None:
        self.workspace = workspace

    def _keys(self, params: JoinParams, left, right) -> tuple[str, str] | ToolError:
        if params.left_key is None and params.right_key is None:
            common = [c for c in left.frame.columns if c in set(right.frame.columns)]
            if len(common) != 1:
                return ToolError(error_code="INVALID_ARGS", layer="reference", candidates=[str(c) for c in common],
                                 message=("Birleştirme anahtarı belirsiz: " + (f"ortak kolonlar {', '.join(map(str, common))}" if common else "ortak adlı kolon yok")
                                          + ". Kullanıcıya hangi kolonla birleştirileceğini sor."))
            return str(common[0]), str(common[0])
        lk = params.left_key or params.right_key
        rk = params.right_key or params.left_key
        assert lk is not None and rk is not None
        if lk not in left.frame.columns:
            return ToolError(error_code="COLUMN_NOT_FOUND", layer="reference", candidates=list(map(str, left.frame.columns)),
                             message=f"'{lk}' {left.id} tablosunda yok.")
        if rk not in right.frame.columns:
            return ToolError(error_code="COLUMN_NOT_FOUND", layer="reference", candidates=list(map(str, right.frame.columns)),
                             message=f"'{rk}' {right.id} tablosunda yok.")
        return lk, rk

    def validate_refs(self, params: JoinParams) -> ToolError | None:
        left, right = self.workspace.source(params.left), self.workspace.source(params.right)
        known = ["aktif", *[s.id for s in self.workspace.sources()]]
        if left is None or right is None:
            return ToolError(error_code="INVALID_ARGS", layer="reference", candidates=known,
                             message=f"Oturumda böyle tablo yok: {params.left if left is None else params.right}.")
        if params.left == params.right:
            return ToolError(error_code="INVALID_ARGS", layer="schema", message="Bir tablo kendisiyle birleştirilmez.")
        keys = self._keys(params, left, right)
        return keys if isinstance(keys, ToolError) else None

    # ------------------------------------------------------------------ anahtar kuralı
    def _policy_problem(self, lcol: pd.Series, rcol: pd.Series, lkind: str, rkind: str, lk: str, rk: str,
                        left_id: str, right_id: str) -> ToolResult | None:
        """Varsayılan 'tam' kuralında tip farkı ya da sonucu değiştiren başka kural varsa birleştirme yapılmaz, sorulur."""
        pair = "|".join(sorted({lkind, rkind})) if lkind != rkind else lkind
        options = _ALTERNATIVES.get(pair, ())
        exact = 0
        if lkind == rkind:
            try:
                exact = _match_count(key_values(lcol, "tam", lkind), key_values(rcol, "tam", rkind))
            except KeyError_ as exc:
                return ToolResult.fail("INVALID_ARGS", f"'{lk}' / '{rk}' anahtarı kayıpsız karşılaştırılamıyor: {exc}.",
                                       hint="Kullanıcıya kimlik kolonunun kaynakta nasıl yazıldığını sor; doğruluk iddia etme.",
                                       layer="data", retryable=False)
        counts: list[tuple[str, int]] = []
        for opt in options:
            try:
                counts.append((opt, _match_count(key_values(lcol, opt, lkind), key_values(rcol, opt, rkind))))
            except KeyError_:
                continue
        better = [(o, n) for o, n in counts if n > exact]
        if lkind != rkind:
            detail = "; ".join(f"key_policy='{o}' ({POLICY_TEXT[o]}) ile {n} sol satır eşleşir" for o, n in counts) or "uygun dönüşüm yok"
            return ToolResult.fail(
                "INVALID_ARGS",
                f"Anahtar tipleri farklı: {left_id}.{lk} {lkind}, {right_id}.{rk} {rkind}. Birebir eşleme yapılmadı; {detail}.",
                hint="Kullanıcıya hangi eşdeğerliği kabul ettiğini sor; kabul ettiği kuralla key_policy vererek yeniden çağır.",
                candidates=[o for o, _ in counts], layer="data", retryable=False)
        if better:
            lraw = [x for x in lcol.tolist() if not _is_missing(x)]
            rraw = [x for x in rcol.tolist() if not _is_missing(x)]
            example = ""
            opt = better[0][0]
            try:
                rmap: dict[Any, Any] = {}
                for x, k in zip(rraw, key_values(pd.Series(rraw, dtype=object), opt, rkind)):
                    rmap.setdefault(k, x)
                for x, k in zip(lraw, key_values(pd.Series(lraw, dtype=object), opt, lkind)):
                    if k in rmap and rmap[k] != x:
                        example = f" (ör. '{x}' ↔ '{rmap[k]}')"
                        break
            except KeyError_:
                pass
            detail = "; ".join(f"key_policy='{o}' ({POLICY_TEXT[o]}) ile {n}" for o, n in better)
            return ToolResult.fail(
                "INVALID_ARGS",
                f"Anahtar kuralı sonucu değiştiriyor: birebir eşitlikle {exact} sol satır eşleşiyor, {detail}{example}. "
                "Eşdeğerlik varsayılmadı.",
                hint="Kullanıcıya bu farkların aynı kimlik sayılıp sayılmayacağını sor; kabul ederse o key_policy ile yeniden çağır, "
                     "etmezse key_policy='tam' ile değil kullanıcının seçtiği kuralla devam et.",
                candidates=[o for o, _ in better], layer="data", retryable=False)
        return None

    @staticmethod
    def _duplicates(rkeys: list[Any], rf: pd.DataFrame, rk: str, right_id: str, policy: str) -> ToolResult | None:
        positions: dict[Any, list[int]] = {}
        for j, k in enumerate(rkeys):
            if k is not None:
                positions.setdefault(k, []).append(j)
        dups = {k: js for k, js in positions.items() if len(js) > 1}
        if not dups:
            return None
        raw_examples = [str(rf[rk].iloc[js[0]]) for js in list(dups.values())[:5]]
        by_norm = [k for k, js in dups.items() if len({str(rf[rk].iloc[j]) for j in js}) > 1]
        extra = (f" Bunların {len(by_norm)} tanesi yalnız '{policy}' kuralı yüzünden aynı sayıldı "
                 f"(ör. {', '.join(repr(str(rf[rk].iloc[j])) for j in dups[by_norm[0]][:2])}).") if by_norm else ""
        return ToolResult.fail("JOIN_MISMATCH",
                               f"{right_id} tablosunda '{rk}' yinelenen değerler taşıyor ({len(dups)} değer, "
                               f"{sum(len(js) for js in dups.values())} satır; ör. {', '.join(raw_examples)}): birleştirme satırları çoğaltır.{extra}",
                               hint="Önce workspace_query ile tekilleştir (GROUP BY) ya da kullanıcıya hangi satırın alınacağını sor.",
                               layer="data", retryable=False)

    def run(self, params: JoinParams) -> ToolResult:
        left, right = self.workspace.source(params.left), self.workspace.source(params.right)
        assert left is not None and right is not None
        keys = self._keys(params, left, right)
        if isinstance(keys, ToolError):
            return ToolResult(content=keys.message, ok=False, error=keys)
        lk, rk = keys
        lf, rf = left.frame, right.frame                       # kaynaklara yazılmaz; yalnız okunur
        lcol, rcol = lf[lk], rf[rk]
        lkind, rkind = key_kind(lcol), key_kind(rcol)
        policy = params.key_policy
        if policy == "tam":
            # Birebir eşitlikte yinelenen anahtar her gevşek kuralda da yinelenir: önce o söylenir.
            if lkind == rkind:
                try:
                    dup_exact = self._duplicates(key_values(rcol, "tam", rkind), rf, rk, right.id, "tam")
                except KeyError_:
                    dup_exact = None
                if dup_exact is not None:
                    return dup_exact
            problem = self._policy_problem(lcol, rcol, lkind, rkind, lk, rk, left.id, right.id)
            if problem is not None:
                return problem
        try:
            lkeys = key_values(lcol, policy, lkind)
            rkeys = key_values(rcol, policy, rkind)
        except KeyError_ as exc:
            return ToolResult.fail("INVALID_ARGS", f"'{policy}' kuralı bu anahtara uygulanamıyor: {exc}.",
                                   hint="Kullanıcıya başka bir eşleme kuralı sor ya da anahtarı workspace_query ile açıkça dönüştür.",
                                   layer="data", retryable=False)

        # Sağda yinelenen anahtar (kural uygulandıktan sonra) satırları çoğaltır.
        dup = self._duplicates(rkeys, rf, rk, right.id, policy)
        if dup is not None:
            return dup
        rmap: dict[Any, int] = {}
        for j, k in enumerate(rkeys):
            if k is not None:
                rmap.setdefault(k, j)

        # Varsayılan seçim kanıt sütunlarını taşımaz (23 Eyl senaryo koşusu: Gold tablosunun gözlem tarihi listeleri ve
        # artifact özetleri kullanıcı tablosuna "_k2" sütunları olarak girdi). Açıkça istenirse columns ile alınır.
        evidence_suffixes = ("::series_id", "::quality_flag", "::measure_type", "::unit", "::aggregation",
                             "::observations", "::missing_observations", "::warned_observations",
                             "::source_observation_dates", "::artifact_sha256_list", "::vintage_id_list", "::run_id_list")
        evidence_names = {"quality_flag", "observations", "missing_observations", "warned_observations",
                          "source_observation_dates", "artifact_sha256_list", "vintage_id_list", "run_id_list",
                          "contributing_series", "absent_series", "is_complete_period", "period_start"}
        take = list(params.columns) if params.columns else [
            c for c in rf.columns if c != rk
            and str(c) not in evidence_names and not str(c).endswith(evidence_suffixes)]
        missing = [c for c in take if c not in rf.columns]
        if missing:
            return ToolResult.fail("COLUMN_NOT_FOUND", f"{right.id} tablosunda yok: {', '.join(map(str, missing))}.",
                                   candidates=list(map(str, right.frame.columns)), layer="reference")
        used = {str(c) for c in lf.columns}
        final_names: list[Any] = []
        renamed: dict[Any, str] = {}
        for c in take:
            name: Any = c
            if str(c) in used:
                base = f"{c}_{right.id}"
                name, n = base, 2
                while name in used:
                    name, n = f"{base}_{n}", n + 1
                renamed[c] = name
            used.add(str(name))
            final_names.append(name)

        lpos = [rmap.get(k) if k is not None else None for k in lkeys]
        both = sum(1 for p in lpos if p is not None)
        if both == 0:
            return ToolResult.fail("JOIN_MISMATCH", f"'{lk}' ile '{rk}' değerleri '{policy}' kuralıyla hiç eşleşmedi.",
                                   hint="İki kolonun örnek değerlerini workspace_query ile karşılaştır; biçim farkıysa kullanıcıya "
                                        "hangi eşdeğerliği kabul ettiğini sor.", layer="data")
        rsel = rf[take].reset_index(drop=True)
        rsel.columns = final_names
        lkey_set = {k for k in lkeys if k is not None}
        if params.how == "inner":
            keep = [i for i, p in enumerate(lpos) if p is not None]
            base = lf.iloc[keep].reset_index(drop=True)
            rows = [lpos[i] for i in keep]
        else:
            base = lf.reset_index(drop=True)
            rows = lpos
        right_part = rsel.reindex(pd.Index([p if p is not None else -1 for p in rows])).reset_index(drop=True)
        merged = pd.concat([base, right_part], axis=1)
        right_only_pos = [j for j, k in enumerate(rkeys) if k is None or k not in lkey_set]
        if params.how == "outer" and right_only_pos:
            extra_rows = lf.iloc[0:0].reindex(range(len(right_only_pos)))
            extra_rows[lk] = rf[rk].iloc[right_only_pos].to_numpy()
            extra = pd.concat([extra_rows.reset_index(drop=True), rsel.iloc[right_only_pos].reset_index(drop=True)], axis=1)
            merged = pd.concat([merged, extra], ignore_index=True)

        left_null = sum(1 for k in lkeys if k is None)
        right_null = sum(1 for k in rkeys if k is None)
        left_only = sum(1 for k, p in zip(lkeys, lpos) if p is None)
        right_unmatched = len(right_only_pos)
        dup_left = len(lkeys) - left_null - len({k for k in lkeys if k is not None})

        rule = f"{left.id}.{lk} = {right.id}.{rk} · kural: {policy} — {POLICY_TEXT[policy]}"
        col_prov = dict(left.provenance)
        for c, name in zip(take, final_names):
            if c in right.provenance:
                p = right.provenance[c]
                col_prov[name] = replace(p, sql=f"{p.sql}\n-- workspace_join {rule}")
        sid = self.workspace.set_table(merged, description=params.purpose, column_provenance=col_prov)
        self.workspace.title = params.purpose
        notes = []
        if left_only:
            notes.append(f"{left_only} {left.id} satırı {right.id} içinde eşleşmedi" + (" (değerleri boş)" if params.how != "inner" else " (sonuca girmedi)")
                         + (f"; bunların {left_null} tanesinin anahtarı boş" if left_null else ""))
        if right_unmatched:
            notes.append(f"{right_unmatched} {right.id} satırı {left.id} içinde eşleşmedi"
                         + (" (sonuç tablosuna girmedi)" if params.how in ("left", "inner") else "")
                         + (f"; bunların {right_null} tanesinin anahtarı boş" if right_null else ""))
        if left_null or right_null:
            notes.append("boş anahtarlar hiçbir satırla eşleştirilmedi (bilinmeyen kimlik aynı varlık sayılmaz)")
        if dup_left:
            notes.append(f"{left.id} tablosunda '{lk}' {dup_left} kez yineleniyor: aynı sağ değer her birine yazıldı (çoktan-bire)")
        if renamed:
            notes.append("ad çakışması: " + ", ".join(f"{a} → {b}" for a, b in renamed.items()))
        card = [
            f"BİRLEŞTİRME: {left.id} ⟕ {right.id} · anahtar {lk} = {rk} · {params.how} · sonuç {sid}: {len(merged)} satır, {len(merged.columns)} kolon",
            f"Anahtar kuralı: {policy} — {POLICY_TEXT[policy]} (tipler: {lkind} / {rkind})",
            f"Eşleşen {both} · yalnız solda {left_only} · yalnız sağda {right_unmatched}",
            *notes,
            "Eklenen kolonlar: " + ", ".join(map(str, final_names)),
            f"Kaynak tablolar {left.id} ve {right.id} değişmedi.",
            "İlk 5 satır:\n" + merged.head(5).to_string(index=False),
        ]
        return ToolResult(content="\n".join(card), data=merged)


__all__ = ["JoinParams", "KeyPolicy", "WorkspaceJoinTool", "key_kind", "key_values"]
