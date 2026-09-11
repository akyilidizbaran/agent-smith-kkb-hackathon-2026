# Motor benchmark protokolü — iki mimariyi adil karşılaştırma

> Kim için: Baran (ekip motoru, `feature/agent-engine`) ve Büşra (V3 motoru, `feature/busra/agent-v3`).
> Amaç: iki motor bağımsız gelişirken **aynı soru, aynı veri, aynı ölçüt** ile karşılaştırılabilir kalsın; kararı ölçüm versin, tartışma değil.
> Etiketler: `[EMP]` ölçüldü · `[SRC]` kaynaktan · `[INF]` çıkarım · `[REC]` öneri

## 1. Bir cümle

`agent-core/scripts/run_benchmark.py --engine team --engine v3 --set all --repeat 3` iki motoru aynı DuckDB üstünde, aynı 18 vakayla (7 golden + 11 alt-küme) üçer kez koşar; **DURUM** üzerinden puanlar (üretilen tablo, kullanılan araç, SQL içeriği), serbest metni puanlamaz; `docs/experiments/benchmark_<set>_<tarih>.md/.json` yazar.

## 2. V3 motoru ne yapıyor — 6 mekanizma (ayrıntı: `ARCHITECTURE_V3.md`)

| Mekanizma | Ne | Ölçülen etkisi `[EMP]` |
|---|---|---|
| Katalog ön-yükleme | Tablo kartları + kırılım kolonlarının gerçek değerleri prompt'ta (≤6k token; üstünde dizin + keşif araçları) | Keşif turları kalkıyor: LLM turu 6,9 → 3,9 (Blok C) |
| Batched ReAct | Bağımsız araç çağrıları aynı turda, thread pool'da paralel; tabloyu değiştirenler sıralı | Yalnız ön-yüklemeyle birlikte faydalı (tek başına 6/7) |
| Sınır doğrulayıcı | Her çağrı: şema → SQL guard → referans (seri/kolon/dönem/alt toplam) → politika; sorgu çalışmadan reddedilir | Hatalar kodlu: `SERIES_NOT_FOUND / OUT_OF_COVERAGE / MISSING_PERIOD_FILTER / DOUBLE_COUNT / UNSAFE_SQL …` |
| Tek hata zarfı | `ToolError(error_code, message, hint, candidates, retryable)`; `retryable=false` → araçsız cevap turu | Modele giden gözlem kısa, düzeltme adayları hazır |
| Grounding guard | Cevaptaki her sayı araç çıktısında var mı (±%0,5); nedensellik dili filtresi; bir kez yeniden üretim, sonra caveat | 41/45 temiz; kafadan hesap yakalanıyor |
| Döngü kilidi | Aynı araç + aynı argüman ikinci kez çalıştırılmaz; üçüncüde araçsız cevap | L4-01: 9 tur/limit → 4 tur/geçti |

Paylaşılan ve **değiştirilmeyen** katman: `kkb_agent.contracts/*`, `adapters/duckdb_lakehouse.py`, `core/workspace.py`, `DomainProfile`, `tools/workspace.py` (V3 sarar), `tests/golden/cases.py`, seed verisi. Domain bilgisi `kkb_agent_v3/domain/finance.md` (markdown; `health.md` boş şablon).

## 3. Son ölçüm (11 Eylül, ekip motoru ADR-0024/0025 sonrası, iki şema) `[EMP]`

| | Ekip motoru · seed | V3 · seed | Ekip motoru · Silver | V3 · Silver |
|---|---|---|---|---|
| vaka pass^3 | 14/18 (45/54) | **17/18** (51/54) | 13/18 (45/54) | **16/18** (48/54) |
| ort. süre | 9,5 s | 7,9 s* | 8,4 s | **3,7 s** |
| p50 süre | 8,1 s | 5,6 s | 7,1 s | 3,1 s |
| LLM turu | 5,7 | 3,1 | 5,4 | 2,9 |
| araç adımı | 5,0 | 1,5 | 4,7 | 1,3 |
| araç hatası | 17 | 13 | 33 (`SQL_FAILED×21`) | 15 |
| anlatı doğrulama | yok | 43/45 | yok | 45/45 |

\* V3 seed ortalaması G5'teki tek 103 s'lik koşuyu içeriyor: cevap turunda model bozuk çıktı üretip durmadı; harness'ta üretim tavanı yoktu → `max_tokens=700` eklendi (bu ölçümden sonra). Onsuz seed ortalaması ≈ 6 s.

Düşen vakalar: L10-01 ikisinde de (`clarify` yok). Ekip motoru ayrıca L6-04 (yıllık özet sorgusu aktif tabloyu 1 satıra indiriyor), L9-02 (Silver'da `FROM <series_id>` yazıp `SQL_FAILED`, sonra 2026'nın 6 ayını tablo yapıyor), L4-01 (adım limiti), G4/L11-02 Silver'da 2/3. V3 Silver'da G3 (0/3): LAG çapası için Aralık 2024'ü tabloya kattı → 13 satır, golden 12 istiyor; analitik olarak savunulabilir, kural eklenmedi. MIA gecikmesi günden güne değişiyor (aynı ekip motoru dün 5,7 s, bugün 9,5 s) — **yalnız aynı koşu içindeki oranlar** karşılaştırılır. Kaynak: `docs/experiments/benchmark_all_2026-09-11_{seed,silver}_r3.md/.json` (adım düzeyi ayrıntı JSON'da). Önceki ölçüm (10 Eylül): `benchmark_all_2026-09-10_r3.md`, `_r3_v3fix.md`.

## 4. Motorun benchmark'a girmesi için sözleşme

Herhangi bir motor şu arayüzü sağlıyorsa koşucuya eklenir; iç mimari serbesttir.

```python
def build_agent(max_steps: int) -> Agent   # her vaka için TAZE motor (temiz workspace)
agent.ask(question: str) -> Answer
Answer.text: str                            # nihai cevap
Answer.steps: list[Step]                    # her araç çağrısı bir Step; nihai cevap da bir Step olabilir
Answer.hit_step_limit: bool
Answer.extra: dict                          # opsiyonel: llm_turns, tokens, grounding, error_codes
Step.index: int                             # LLM turu numarası (LLM turu sayımı buradan)
Step.tool_name: str | None
Step.tool_args: dict                        # lakehouse_query için {"sql": ...} beklenir
Step.ok: bool
Step.error_code: str | None                 # opsiyonel
agent.workspace.table -> pandas.DataFrame | None   # golden tablo kontrolleri buradan
```

Kontrollerin beklediği araç adları: `lakehouse_query` (argüman `sql`), `workspace_add_column`, `workspace_compute_column`. Adların farklıysa **motor kodunu değiştirme**, koşucudaki `TOOL_ALIASES["<motor>"]`'a eşleme yaz:

```python
TOOL_ALIASES = {"team": {}, "v3": {}, "baran_v2": {"run_sql": "lakehouse_query", "add_col": "workspace_add_column"}}
ENGINES["baran_v2"] = lambda: baran_v2.build_agent(max_steps=12)
```

Kayıt yeri: `agent-core/scripts/run_benchmark.py` → `_load_engines()`.

## 5. Koşu kuralları (adillik)

1. **Aynı veri**: `agent-core/data/lakehouse.duckdb` + `catalog.json` (`python scripts/dev_seed.py`, BDDK Tablo 3–4). Data ekibinin Silver adaptörü gelince ikisi de ona geçer; karışık koşu yok.
2. **Aynı model ayarları**: `.env`'deki `LLM_MODEL`, `LLM_DISABLE_THINKING=true`; koşu başlığına model yazılır. Motor içi `reasoning_effort` yükseltmesi serbesttir ama raporda belirtilir.
3. **Sıralı koşu**: motorlar arka arkaya, aynı anda değil — MIA'yı paylaşmak gecikmeyi bozar (10 Eylül'de gözlendi: eşzamanlı koşuda 4 turluk vaka 17 s'ye çıktı `[EMP]`).
4. **repeat=3, pass^3**: bir vaka üç koşuda da geçmedikçe "geçti" sayılmaz (τ-bench pass^k `[SRC]`).
5. **Adım bütçesi**: her motor kendi varsayılanıyla (ekip 12 adım, V3 8 tur); bütçe aşımı başarısızlıktır ve raporda görünür.
6. **Soru setine göre ayar yasağı**: golden ve alt-küme soruları herkese açık; bir motoru bu sorulara göre prompt'la "ezberletmek" karşılaştırmayı bozar. Yeni vaka eklemek serbest ama **koşudan önce, birlikte**, `tests/golden/cases.py` (durum kontrolüyle) ya da koşucudaki `SUBSET`'e.
7. **Sonuç commit'lenir**: `docs/experiments/benchmark_<set>_<tarih>[_etiket].md/.json`; hangi motor hangi commit'te koştu, md'nin başına yazılır.

## 6. Karar kuralı `[REC]`

Sırayla, ilk farklılaşan kazanır:

1. **pass^3** (vaka sayısı) — doğruluk kapısı; düşük olan elenir.
2. **Doğrulanmış anlatı** — cevaptaki sayılar araç çıktısıyla eşleşiyor mu (koşucu ölçüyor: `grounding temiz`). Jüri "güven katmanı" istiyor; sayı uyduran hızlı motor kaybeder.
3. **LLM turu ve süre** — düşük olan.
4. Eşitlikte: bakım maliyeti (satır sayısı, test sayısı, ekibin okuyabilmesi).

Kazanan motor ana omurga olur; kaybedenin işe yarayan parçaları taşınır. Sınır doğrulayıcı, grounding guard ve hata zarfı **motordan bağımsız modüller** — Baran'ın motoruna da takılabilir (`kkb_agent_v3/core/validator.py`, `grounding.py`, `errors.py`).

## 7. Baran için adım adım

```bash
git fetch && git checkout feature/busra/agent-v3        # sadece bakmak için; kendi dalında çalışmaya devam
cd agent-core && python scripts/dev_seed.py            # bir kez
python -m pytest tests -q                              # 86 test geçmeli
PYTHONPATH=src python scripts/run_benchmark.py --engine team --engine v3 --set all --repeat 3
```

Kendi motorun değiştiyse: `_load_engines()`'a kaydet, gerekiyorsa `TOOL_ALIASES` yaz, aynı komutu `--engine team --engine v3 --engine <senin>` ile koş. Vaka bazında tabloya bak; bir vaka bir motorda düşüyorsa JSON'daki `steps` (tur, araç, argüman, sonuç) nedenini gösterir.

## 8. Bilinen sınırlar

- 18 vaka tek tablo (BDDK) üzerinde; çok serili (L5), dış kanıtlı (L7, L12) ve sağlık şeması (L8) vakaları data ekibinin serileri ve yeni araç aileleri gelmeden koşamaz.
- Grounding ölçümü yalnız V3'te var; ekip motoru için gölge ölçüm eklenebilir (koşucuya `tool_texts` toplamak yeter) `[REC]`.
- Süre ölçümleri MIA yüküne bağlı; aynı oturumda, arka arkaya koşulan sonuçlar karşılaştırılır, farklı günler değil.
