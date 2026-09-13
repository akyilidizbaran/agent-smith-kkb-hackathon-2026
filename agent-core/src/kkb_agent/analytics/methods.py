"""Deterministik analitik yöntemler — LLM yok, numpy/scipy var.

Yarışmanın asgari araç listesinde üçü adıyla geçiyor: Anomali, Causality, Change Detection.
Literatürün tutarlı bulgusu (ve bizim ölçümümüz, ADR-0027): dil modeli sayısal girdi üzerinde
kendi aritmetiğini yapınca uydurur. Burada istatistik tespit eder, model yalnız kartı anlatır.

Üç yöntem, hepsi tek boyutlu sayı dizisi üzerinde, hepsi sentetik seriyle test edilir:

* ``detect_anomalies``  — IQR ya da z-skoru; trendli seride (stok bakiye gibi) düzey değil
  DEĞİŞİM üzerinde çalışır, yoksa yükselen serinin iki ucu "aykırı" çıkar (ölçüldü).
* ``detect_change_points`` — ikili bölütleme (binary segmentation), parçalı sabit ortalama,
  ceza log(n) ölçekli; trendli seride büyüme hızının rejim değişimini bulur.
* ``lead_lag`` — gecikmeli Pearson korelasyonu (+k: A, B'den k dönem ÖNCE hareket ediyor) ve
  Granger öncüllük F-testi iki yönde. Çıktı "öncülük"tür, nedensellik değil; kart öyle der.

"basis" kararı deterministik: Spearman |rho|(sıra, değer) ≥ 0.8 ise seri trendli sayılır ve
yüzde değişim kullanılır ("change"); aksi hâlde düzey ("level"). Kullanıcı isterse zorlanır.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import stats

TREND_RHO = 0.8
_EPS = 1e-12


# ----------------------------------------------------------------------------- yardımcılar
def pct_changes(values: np.ndarray) -> np.ndarray:
    """Yüzde değişim (×100); ilk eleman NaN.

    M12-T05: payda |önceki| (negatif tabanda yön doğru kalır: −10 → −5 artıştır, +%50); işaret değiştiren
    dönemde (−5 → +5) ya da sıfır tabanda yüzde değişim anlamsızdır → NaN (aykırı değil, hesaplanamadı).
    """
    v = np.asarray(values, dtype=float)
    out = np.full(v.shape, np.nan)
    prev, cur = v[:-1], v[1:]
    crosses = (np.sign(prev) * np.sign(cur)) < 0
    with np.errstate(divide="ignore", invalid="ignore"):
        out[1:] = np.where((np.abs(prev) > _EPS) & ~crosses, (cur - prev) / np.abs(prev) * 100.0, np.nan)
    return out


def has_non_positive(values: np.ndarray) -> bool:
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    return bool(len(v)) and bool((v <= 0).any())


def trend_strength(values: np.ndarray) -> float:
    """|Spearman rho| (sıra ↔ değer). 1'e yakınsa seri tekdüze yükseliyor/düşüyor."""
    v = np.asarray(values, dtype=float)
    mask = ~np.isnan(v)
    if mask.sum() < 3 or np.nanstd(v) < _EPS:
        return 0.0
    rho = stats.spearmanr(np.arange(len(v))[mask], v[mask]).statistic
    return float(abs(rho)) if rho == rho else 0.0


def choose_basis(values: np.ndarray, basis: str = "auto") -> tuple[str, float]:
    rho = trend_strength(values)
    if basis in ("level", "change"):
        return basis, rho
    if has_non_positive(values):
        return "level", rho          # sıfır/negatif içeren seride yüzde değişim tabanı anlamsız (M12-T05)
    return ("change" if rho >= TREND_RHO else "level"), rho


def _series_on_basis(values: np.ndarray, basis: str) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    return pct_changes(v) if basis == "change" else v


# ----------------------------------------------------------------------------- aykırılık
@dataclass(frozen=True)
class AnomalyResult:
    flags: np.ndarray          # bool, orijinal konumlarla hizalı
    scores: np.ndarray         # z-skoru ya da IQR birimi cinsinden işaretli uzaklık (NaN: hesaplanamadı)
    analysed: np.ndarray       # üzerinde çalışılan dizi (düzey ya da % değişim)
    method: str
    basis: str
    threshold: float
    lower: float
    upper: float
    trend_rho: float

    @property
    def count(self) -> int:
        return int(self.flags.sum())


def detect_anomalies(values: np.ndarray, *, method: str = "iqr", basis: str = "auto",
                     threshold: float | None = None) -> AnomalyResult:
    """IQR (Tukey çiti, k=1.5) ya da z-skoru (|z| > 3). Eşik NaN'ları saymaz."""
    v = np.asarray(values, dtype=float)
    chosen, rho = choose_basis(v, basis)
    x = _series_on_basis(v, chosen)
    ok = ~np.isnan(x)
    scores = np.full(x.shape, np.nan)
    flags = np.zeros(x.shape, dtype=bool)
    if ok.sum() < 4:
        return AnomalyResult(flags, scores, x, method, chosen, float(threshold or 0), np.nan, np.nan, rho)
    if method == "zscore":
        k = 3.0 if threshold is None else float(threshold)
        mu, sd = float(np.mean(x[ok])), float(np.std(x[ok], ddof=1))
        if sd < _EPS:
            return AnomalyResult(flags, scores, x, method, chosen, k, mu, mu, rho)
        scores[ok] = (x[ok] - mu) / sd
        lower, upper = mu - k * sd, mu + k * sd
        flags[ok] = np.abs(scores[ok]) > k
        return AnomalyResult(flags, scores, x, method, chosen, k, lower, upper, rho)
    k = 1.5 if threshold is None else float(threshold)
    q1, q3 = np.percentile(x[ok], [25, 75])
    iqr = float(q3 - q1)
    lower, upper = float(q1 - k * iqr), float(q3 + k * iqr)
    if iqr < _EPS:
        # Çeyrekler arası açıklık sıfır (ör. sabit büyüme + tek sıçrama): IQR körleşir,
        # z-skoruna düşülür; kart yöntemi "zscore (IQR sıfır)" diye yazar.
        z = detect_anomalies(v, method="zscore", basis=chosen, threshold=None)
        return AnomalyResult(z.flags, z.scores, z.analysed, "zscore (IQR sıfır)", chosen, z.threshold, z.lower, z.upper, rho)
    xs = x[ok]
    s = np.where(xs > q3, (xs - q3) / iqr, np.where(xs < q1, (xs - q1) / iqr, 0.0))
    scores[ok] = s
    flags[ok] = (xs > upper) | (xs < lower)
    return AnomalyResult(flags, scores, x, "iqr", chosen, k, lower, upper, rho)


# ----------------------------------------------------------------------------- kırılma
@dataclass(frozen=True)
class Segment:
    start: int   # dâhil (orijinal konum)
    end: int     # dâhil
    mean: float
    n: int


@dataclass(frozen=True)
class ChangePointResult:
    breaks: list[int]              # yeni rejimin başladığı orijinal konumlar
    segments: list[Segment]
    analysed: np.ndarray
    basis: str
    penalty: float
    trend_rho: float
    jumps: list[int] = field(default_factory=list)   # yüzde tabanında tek dönemlik düzey sıçramaları (indeks)


def _sse(x: np.ndarray) -> float:
    return float(np.sum((x - x.mean()) ** 2)) if len(x) else 0.0


def _best_split(x: np.ndarray, min_size: int) -> tuple[int, float]:
    """En çok SSE düşüren bölme noktası (ikinci parçanın başlangıcı) ve kazancı."""
    n = len(x)
    if n < 2 * min_size:
        return -1, 0.0
    total = _sse(x)
    best_i, best_gain = -1, 0.0
    for i in range(min_size, n - min_size + 1):
        gain = total - _sse(x[:i]) - _sse(x[i:])
        if gain > best_gain:
            best_i, best_gain = i, gain
    return best_i, best_gain


def binary_segmentation(x: np.ndarray, *, min_size: int = 4, max_breaks: int = 3,
                        penalty: float | None = None) -> tuple[list[int], float]:
    """Parçalı sabit ortalama için ikili bölütleme. Kazanç > ceza olan bölmeler kabul edilir.

    Ceza varsayılanı 2·log(n)·σ² (σ: birinci farkların MAD'ından, sağlam): gürültü seviyesinde
    ölçeklenir, birim bağımsız. Sentetik testte ±1 gürültülü 100 noktada 3σ'lık sıçrama bulunur,
    saf gürültüde kırılma bulunmaz.
    """
    n = len(x)
    if n < 2 * min_size:
        return [], 0.0
    if penalty is None:
        # σ: birinci farkların MAD'ından (düzey kaymalarından etkilenmez; serinin kendi MAD'ı gerçek
        # rejim değişimlerini gürültü sayıp cezayı şişiriyordu — ölçüldü, 66 aylık konut serisinde
        # görünür rejimler bulunamadı). Ceza BIC ölçeğinde 2·log(n)·σ².
        d = np.diff(x)
        mad = float(np.median(np.abs(d - np.median(d)))) / np.sqrt(2.0) if len(d) else 0.0
        if mad <= _EPS:
            mad = float(np.median(np.abs(x - np.median(x))))
        sigma = 1.4826 * mad if mad > _EPS else float(np.std(x)) or 1.0
        penalty = 2.0 * np.log(n) * sigma * sigma
    breaks: list[int] = []
    intervals: list[tuple[int, int]] = [(0, n)]   # [start, end)
    while intervals and len(breaks) < max_breaks:
        # her turda tüm aralıklar içinde en büyük kazançlı bölme
        cand = []
        for (a, b) in intervals:
            i, gain = _best_split(x[a:b], min_size)
            if i > 0 and gain > penalty:
                cand.append((gain, a + i, a, b))
        if not cand:
            break
        gain, pos, a, b = max(cand)
        breaks.append(pos)
        intervals.remove((a, b))
        intervals += [(a, pos), (pos, b)]
    return sorted(breaks), float(penalty)


def level_jumps(x: np.ndarray, *, z: float = 8.0, floor: float = 1.0, max_jumps: int = 3, k: int = 3) -> list[int]:
    """Yüzde değişim tabanında tek dönemlik düzey sıçramaları (dürtü): değer hem önceki hem sonraki k gözlemin
    medyanından çok uzak, o iki yerel medyan ise birbirine yakın. Ölçek: birinci farkların MAD'ı (sağlam gürültü).

    M16 ölçümü (14 Eyl): trendli seride 2025-01'deki düzey kırılması yüzde tabanında TEK bir büyük değişime dönüşüyor;
    en az 4 gözlemlik bölüt kuralı onu Ekim 2024'te başlayan bir "rejime" gömüyor ve kırılma üç ay erken görünüyordu.
    Büyüme hızının kalıcı değişimi (0,5% → 3%) dürtü değildir: sonraki medyan da yeni düzeydedir, bölütleme bulur.
    Sıçrama ayrı kırılma sayılır, bölütlemeye medyanla girer. Saf gürültüde z>8 pratikte görülmez."""
    n = len(x)
    if n < 2 * k + 1:
        return []
    d = np.diff(x)
    scale = max(1.4826 * float(np.median(np.abs(d - np.median(d)))) / np.sqrt(2.0), 1e-9)
    cand: list[tuple[float, int]] = []
    for i in range(n):
        left, right = x[max(0, i - k):i], x[i + 1:i + 1 + k]
        if len(left) < 2 or len(right) < 2:
            continue
        lm, rm = float(np.median(left)), float(np.median(right))
        dev = min(abs(x[i] - lm), abs(x[i] - rm))
        if dev >= floor and dev > z * scale and abs(lm - rm) < dev / 4:
            cand.append((dev, i))
    return sorted(i for _, i in sorted(cand, reverse=True)[:max_jumps])


def detect_change_points(values: np.ndarray, *, basis: str = "auto", min_size: int = 4,
                         max_breaks: int = 3) -> ChangePointResult:
    v = np.asarray(values, dtype=float)
    chosen, rho = choose_basis(v, basis)
    x_full = _series_on_basis(v, chosen)
    ok = np.where(~np.isnan(x_full))[0]
    x = x_full[ok]
    jumps_local = level_jumps(x) if chosen == "change" else []
    xs = x.copy()
    if jumps_local:
        xs[jumps_local] = float(np.median(np.delete(x, jumps_local)))
    seg_local, pen = binary_segmentation(xs, min_size=min_size, max_breaks=max_breaks)
    # Sıçramanın min_size komşuluğundaki bölütleme kırılması aynı olaydır; sıçrama önceliklidir.
    extra = [b for b in seg_local if all(abs(b - j) >= min_size for j in jumps_local)]
    breaks_local = sorted(set(jumps_local) | set(extra[: max(0, max_breaks - len(jumps_local))]))
    breaks = [int(ok[i]) for i in breaks_local]
    bounds = [0, *breaks_local, len(x)]
    segments = [
        Segment(start=int(ok[bounds[j]]), end=int(ok[bounds[j + 1] - 1]),
                mean=float(np.mean(xs[bounds[j]:bounds[j + 1]])), n=int(bounds[j + 1] - bounds[j]))
        for j in range(len(bounds) - 1)
    ] if len(x) else []
    return ChangePointResult(breaks, segments, x_full, chosen, pen, rho, jumps=[int(ok[i]) for i in jumps_local])


# ----------------------------------------------------------------------------- öncül-ardıl
@dataclass(frozen=True)
class GrangerResult:
    direction: str      # "A→B" ya da "B→A"
    lag: int
    f_stat: float
    p_value: float
    n_used: int


@dataclass(frozen=True)
class LeadLagResult:
    lags: list[int]
    correlations: list[float]     # lag k>0: A, B'den k dönem önce (corr(A[t-k], B[t]))
    best_lag: int
    best_r: float
    n: int
    basis: str
    granger: list[GrangerResult] = field(default_factory=list)
    trend_rho: tuple[float, float] = (0.0, 0.0)


def cross_correlation(a: np.ndarray, b: np.ndarray, max_lag: int) -> tuple[list[int], list[float]]:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    lags, rs = [], []
    for k in range(-max_lag, max_lag + 1):
        if k >= 0:
            x, y = a[: len(a) - k] if k else a, b[k:]
        else:
            x, y = a[-k:], b[: len(b) + k]
        m = ~(np.isnan(x) | np.isnan(y))
        if m.sum() < 5 or np.std(x[m]) < _EPS or np.std(y[m]) < _EPS:
            r = np.nan
        else:
            r = float(np.corrcoef(x[m], y[m])[0, 1])
        lags.append(k)
        rs.append(r)
    return lags, rs


def granger_test(x: np.ndarray, y: np.ndarray, lag: int) -> GrangerResult | None:
    """x, y'yi Granger anlamında önceliyor mu? Kısıtlı (yalnız y gecikmeleri) ve kısıtsız
    (+ x gecikmeleri) OLS; F = ((SSR_r − SSR_u)/lag) / (SSR_u/(n − 2·lag − 1))."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)
    if lag < 1 or n - lag < 3 * lag + 5:
        return None
    rows = []
    for t in range(lag, n):
        rows.append((y[t], *[y[t - j] for j in range(1, lag + 1)], *[x[t - j] for j in range(1, lag + 1)]))
    m = np.array(rows, dtype=float)
    m = m[~np.isnan(m).any(axis=1)]
    n_used = len(m)
    if n_used < 3 * lag + 5:
        return None
    target = m[:, 0]
    ones = np.ones((n_used, 1))
    xr = np.hstack([ones, m[:, 1:lag + 1]])
    xu = np.hstack([ones, m[:, 1:]])

    def ssr(design: np.ndarray) -> float:
        coef, *_ = np.linalg.lstsq(design, target, rcond=None)
        return float(np.sum((target - design @ coef) ** 2))

    ssr_r, ssr_u = ssr(xr), ssr(xu)
    df2 = n_used - 2 * lag - 1
    if df2 <= 0 or ssr_u < _EPS:
        return None
    f = ((ssr_r - ssr_u) / lag) / (ssr_u / df2)
    p = float(stats.f.sf(f, lag, df2))
    return GrangerResult(direction="", lag=lag, f_stat=float(f), p_value=p, n_used=n_used)


def lead_lag(a: np.ndarray, b: np.ndarray, *, max_lag: int = 6, basis: str = "auto") -> LeadLagResult:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ba, rho_a = choose_basis(a, basis)
    bb, rho_b = choose_basis(b, basis)
    chosen = "change" if (basis == "change" or (basis == "auto" and (ba == "change" or bb == "change"))) else "level"
    xa, xb = _series_on_basis(a, chosen), _series_on_basis(b, chosen)
    lags, rs = cross_correlation(xa, xb, max_lag)
    valid = [(abs(r), k, r) for k, r in zip(lags, rs) if r == r]
    if not valid:
        return LeadLagResult(lags, rs, 0, float("nan"), 0, chosen, [], (rho_a, rho_b))
    _, best_lag, best_r = max(valid)
    pair_mask = ~(np.isnan(xa) | np.isnan(xb))
    n = int(pair_mask.sum())
    g_lag = max(1, min(max_lag, abs(best_lag) or 1))
    granger: list[GrangerResult] = []
    for direction, (x, y) in (("A→B", (xa, xb)), ("B→A", (xb, xa))):
        res = granger_test(x, y, g_lag)
        if res is not None:
            granger.append(GrangerResult(direction, res.lag, res.f_stat, res.p_value, res.n_used))
    return LeadLagResult(lags, rs, int(best_lag), float(best_r), n, chosen, granger, (rho_a, rho_b))


__all__ = [
    "AnomalyResult", "ChangePointResult", "GrangerResult", "LeadLagResult", "Segment",
    "binary_segmentation", "choose_basis", "cross_correlation", "detect_anomalies",
    "detect_change_points", "granger_test", "lead_lag", "pct_changes", "trend_strength",
]
