# Agent Smith — KKB Hackathon 2026

**Lakehouse Agent Builder and Data Analytics**

Sıfırdan kurulan bir Data Lakehouse ve onun üzerinde çalışan, doğal dildeki soruyu
anlayıp analizi kendi planlayan bir *agentic analytics* motoru.


## Main üzerindeki güncel lakehouse teslimi

Kaynak: `feature/generic-adhoc-ingestion-v1` (`84919cb`). Önceki Elif Güngen katkıları commit geçmişiyle birlikte alınmıştır. Ajan motorunun entegrasyonu ayrı PR ile devam edecektir.

AgentSmithler Workspace is the shared repository for the KKB Agentic Data Analytics
project. The current implemented component is `lakehouse-core/`, a local-first,
generic Python data lakehouse foundation.

### Current state

`lakehouse-core/` provides source access, immutable RAW artifacts, Bronze Parquet,
semantic catalog loading, ingestion observability, and an acceptance-tested,
source-independent Silver V1 observation layer. The first Agent/Data P0 handoff is
also implemented: CPI catalog/Silver support, automatic series coverage, and safe
read-only Agent queries over Silver. Gold P0 is implemented as catalog-driven,
fail-closed functions for frequency alignment, cumulative decomposition, and period joins.
Generic and ad-hoc ingestion V1 is also implemented: unknown CSV, XLSX, JSON-record, and
static HTML inputs can be ingested through a guarded connector/parser path, registered only
as draft/derived catalog entries, and published into an isolated ad-hoc observation table
with durable run-to-artifact provenance.

### Repository map

- `lakehouse-core/`: the analytical lakehouse component.
- `lakehouse-core/src/lakehouse/`: connectors, parsers, storage, catalog, Silver, and shared contracts.
- `lakehouse-core/models/`: SQL models, including the current Silver model.
- `lakehouse-core/schemas/`: formal data contracts.
- `lakehouse-core/docs/`: team, source, catalog, and architecture documentation.
- `lakehouse-core/tests/`: unit, contract, security, infrastructure, and offline integration tests.

For architecture, supported series, setup, and usage, see the
[`lakehouse-core README`](lakehouse-core/README.md).

### Current delivery checkpoints

- Silver V1 acceptance and data-trust closure:
  [`silver-v1-acceptance-pack.md`](lakehouse-core/docs/acceptance/silver-v1-acceptance-pack.md)
- Agent/Data P0 handoff:
  [`agent-data-p0.md`](lakehouse-core/docs/branches/agent-data-p0.md)
- Gold P0 API and branch delivery:
  [`gold-contract.md`](lakehouse-core/docs/gold-contract.md) ·
  [`gold-functions-v1.md`](lakehouse-core/docs/branches/gold-functions-v1.md)
- Generic and ad-hoc ingestion V1:
  [`generic-ingestion-contract.md`](lakehouse-core/docs/generic-ingestion-contract.md) ·
  [`adhoc-publication-contract.md`](lakehouse-core/docs/adhoc-publication-contract.md) ·
  [`generic-adhoc-review-fixes.md`](lakehouse-core/docs/branches/generic-adhoc-review-fixes.md)
- Independent architecture and quality audit:
  [`data-lakehouse-bagimsiz-denetim-raporu-2026-09-10.md`](lakehouse-core/docs/audits/data-lakehouse-bagimsiz-denetim-raporu-2026-09-10.md)

The source branch records **942 passing tests** at its Generic/Ad-hoc checkpoint; this is a historical result, not a new test run for this merge. The remaining
Data/Lakehouse scope is operational CLI/windowing, then catalog/FinTürk expansion and
live-source evidence closure.

---

## Proje hedefi ve başlangıç planı

Aşağıdaki ajan mimarisi ve ajan çalıştırma komutları başlangıç planıdır; ajan kodu henüz bu main tesliminde yoktur. Mevcut bileşenin kurulum ve kullanımı için yukarıdaki lakehouse bağlantısını izleyin.


## Problem

Türkiye'nin açık ekonomi verileri (BDDK, TCMB EVDS) dağınık, farklı frekanslarda ve
farklı birimlerde yayınlanıyor. Bir kısmı kümülatif, bir kısmı değil. Bu haliyle ne bir
analist ne de bir dil modeli doğrudan kullanabilir.

Yarışmanın beklentisi iki katmanlı:

1. Bu veriyi **işlenebilir ve ilişkilendirilebilir** hale getiren, alandan bağımsız
   (jenerik) bir Data Lakehouse.
2. Üzerinde çalışan, soruyu anlayan → analizi planlayan → uygun aracı kullanan →
   sonucu doğrulayan → karar destek çıktısına dönüştüren bir **agentic** çözüm.

Beklenen, yalnızca analiz yapan bir sistem değil; **uçtan uca akıl yürüten** bir sistem.

## Çözüm mimarisi

```
   Açık veri kaynakları                    Doğal dilde soru
   BDDK · EVDS · URL · dosya · PDF/görsel         │
            │                                     ▼
            ▼                          ┌────────────────────────┐
   ┌──────────────────┐                │   Agentic Engine       │
   │  Data Lakehouse  │                │  planla → araç çağır   │
   │                  │                │  → gözlemle → onar     │
   │  RAW (immutable) │                ├────────────────────────┤
   │  Bronze  parquet │                │ Araçlar:               │
   │  Silver  canonic │◀──────────────▶│  lakehouse             │
   │  Gold    analiz  │   Contract     │  web search / URL      │
   │  Meta    catalog │                │  anomali · kırılma     │
   └──────────────────┘                │  öncül-ardıl (Granger) │
                                       │  grafik · ingest       │
                                       └───────────┬────────────┘
                                                   ▼
                                     Tablo · grafik · rapor + KAYNAK
```

İki katman doğrudan birbirine bağlı değil; aralarında yazılı bir **sözleşme** var
([docs/LAKEHOUSE_CONTRACT.md](docs/LAKEHOUSE_CONTRACT.md)). Bu sayede iki ekip birbirini
beklemeden paralel çalışır ve Lakehouse'un iç yapısı değiştiğinde agent etkilenmez.

Aynı ayrım, yarışmanın *"platform jenerik olmalı, içi boşaltılıp bambaşka bir sağlık
verisiyle de çalışabilmeli"* şartını mimari düzeyde karşılar: yeni bir alana geçmek için
yeni bir Lakehouse uygulaması ve yeni bir katalog yazmak yeterlidir, agent aynı kalır.

### Tasarım ilkesi: harness güçlü, modele en az iş

Açılış toplantısındaki yönlendirme netti: *"Harness yapısını daha güçlü yapın, LLM'e en az
işi bırakın."* Buna göre model:

- **hesap yapmaz** — toplama, oran, değişim hepsi SQL'de,
- **ham veri görmez** — şema ve birkaç örnek satır görür, veri motorda kalır,
- **değer uydurmaz** — filtreleyeceği kategorileri katalogdan okur,
- **hatasını yutmaz** — hata metni kendisine döner, çağrısını düzeltir.

Geliştirmede küçük yerel modelle de çalışan bu yapı, demoda KKB'nin MIA/Kloudeks üzerinden verdiği
modellerle (DeepSeek-V4.1-Flash metin, Unlimited-OCR belge/görsel, Qwen3-Embedding-8B) çalışır; sağlayıcı ve model
yalnız `.env` ile değişir (ADR-0103).

### Güven katmanı

Üretilen her sayı; hangi SQL'den, hangi tablodan, hangi kurumun hangi bültenindeki hangi
dönemden geldiği bilgisiyle birlikte taşınır. "Bu rakam nereden geliyor?" sorusu tek adımda
cevaplanabilir.

## Repo yapısı

| Yol | İçerik |
|---|---|
| `agent-core/src/kkb_agent/` | Agentic analytics motoru — [teknik doküman](docs/AGENT.md) |
| `agent-core/src/kkb_agent/contracts/` | Veri katmanıyla sözleşme (Protocol + semantic catalog) |
| `agent-core/src/kkb_agent/core/` | Harness, analiz durumu, araç soyutlaması |
| `agent-core/src/kkb_agent/tools/` | Araçlar — her yetenek bağımsız modül |
| `agent-core/src/kkb_agent/web_app.py` + `static/` | Arayüz: sohbet, kanıt paneli, dosya yükleme, dışa aktarım, profil |
| `agent-core/tests/` | Deterministik birim/sözleşme testleri; `golden/` uçtan uca vakalar, `fixtures/generic/` finans dışı veri |
| `agent-core/scripts/` | Demo verisi kurulumu, golden, M02 kıyası, M16 kabul ve arayüz uçtan uca provası |
| `lakehouse-core/` | Data Lakehouse — ingestion, Bronze/Silver/Gold, semantic catalog |
| `docs/ARCHITECTURE.md` | **Mimari** — katmanlar, sözleşmeler, agent döngüsü, araçlar, jeneriklik garantileri |
| `docs/adr/` | **Mimari karar kayıtları** — her kararın gerekçesi ve ölçümü |
| `docs/MILESTONE_PLANI_2026-09-13.md` | Milestone planı ve işaretli ilerleme (M00–M17) |
| `docs/OPERASYON_TARIFI.md` | Demo günü kurulum, akış, kaynak erişim matrisi, sorun giderme |
| `docs/M16_KABUL_RAPORU.md` | Birleşik kabul raporu (vaka matrisi, canlı koşular, sınırlar) |
| `PROJECT_MEMORY.md` | Adım adım ilerleme kaydı ve ölçülerek öğrenilenler |
| `docs/` | Sözleşme dokümanları, açılış toplantısı slaytları |

## Hızlı başlangıç

Repo kökünde (M01, ADR-0049):

```bash
make setup                    # iki ortam, kilit dosyalarından
cp .env.example .env          # değerleri doldurun — .env asla commit edilmez
make preflight                # salt-okunur ön kontrol; HAZIR DEĞİL ise sebebini söyler
make demo-data                # veri DEĞİŞTİRİR: 681 seri 2016+ canlı ingest → silver → gold (~30 dk)
make serve                    # arayüz: http://127.0.0.1:8765
make ci                       # CI ile aynı deterministik testler
```

Tek soru, izli: `cd agent-core && uv run python -m kkb_agent.cli --trace "2025'te konut kredisi nasıl değişti?"`

Ayrıntı: [docs/AGENT.md](docs/AGENT.md) · demo günü ve kabul betikleri: [docs/OPERASYON_TARIFI.md](docs/OPERASYON_TARIFI.md) · `.env` kabukta `source` edilmez, uygulama okur

## Veri kaynakları

| Kaynak | Kapsam | Erişim |
|---|---|---|
| BDDK Aylık Bülten | 2016-01 → 2026-06, 20 kalem (4 kalem kaynakta 2018'den) | Kimlik doğrulaması olmayan JSON endpoint |
| BDDK Haftalık Bülten | 2016-01 → 2026-06 | dönem bazlı sorgu |
| BDDK FinTürk (il bazlı) | 2016-Ç1 → 2026-Ç2, 81 il × 8 ölçüm | form POST, yalnız çeyrek sonu |
| TCMB EVDS 3 | 2016-01 → 2026-06, 12 seri | `key` başlığıyla REST, ≤365 günlük pencere |
| Ad-hoc dosya / URL | demo anında | CSV / Excel / PDF / görsel (MIA OCR) / HTML |

Yüklü dönemin dışı istenirse Analyst mevcut aralığı söyler; Architect kaynaktan çekebilir. Kapsam ve mutabakat:
[docs/M08_KAPSAM_RAPORU.md](docs/M08_KAPSAM_RAPORU.md).

Endpoint ayrıntıları ve doğrulanmış tablo haritası:
[docs/LAKEHOUSE_CONTRACT.md](docs/LAKEHOUSE_CONTRACT.md) § 5.

## Çalışma düzeni

- `main` — korumalı. Doğrudan geliştirme yapılmaz; ana dala birleştirme ekip kararıyla ve PR üzerinden yapılır.
- `feature/agent-engine` — bütünleşik geliştirme dalı: agent motoru, `lakehouse-core`, arayüz ve belgeler birlikte.
- Diğer `feature/*` dalları ekip üyelerinin çalışma ve araştırma dallarıdır; silinmez.
- Her push'ta GitHub Actions iki paketin deterministik testlerini koşar (`.github/workflows/tests.yml`).

## Kararlar nasıl kayda geçiyor

Her mimari karar, gerekçesi ve varsa ölçümüyle birlikte
[`docs/adr/`](docs/adr/) altına yazılır. Reddedilen kararlar da kayıtta durur:
bir şeyi deneyip ölçerek vazgeçmiş olmak, hiç dememekten farklıdır ve aynı fikir
tekrar gündeme geldiğinde tartışma sıfırdan başlamaz.

## Takvim

| Tarih | Aşama |
|---|---|
| 20 Eylül 2026 | Geliştirme bitişi — repo dondurulur |
| 5 Ekim 2026 | Finalist 10 takımın açıklanması |
| 17 Ekim 2026 | Final sunumları |

## Kurallar

Yarışma şartnamesinden doğan ve ihlali eleme sebebi olan kısıtlar:

- **Hazır/lisanslı bulut Lakehouse kullanılmaz** (Snowflake, BigQuery vb.). Çözüm
  baştan sona bu repoda üretilir.
- **Dış LLM servisi kullanılmaz** (OpenAI, Anthropic, OpenRouter). Yalnızca KKB'nin
  Kloudeks platformu üzerinden erişilen modeller kullanılır.
- **Backend Python.** Frontend serbest. Açık kaynak kütüphaneler tercih edilir.
- **API key'leri repoya yazılmaz** — private repo olsa bile. Tümü `.env` içinde tutulur,
  `.gitignore` ile korunur.
- Repo private kalır; dondurma tarihinden sonra commit atılmaz.
