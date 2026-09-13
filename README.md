# AgentSmithler — KKB Hackathon 2026

**Lakehouse Agent Builder and Data Analytics**

Sıfırdan kurulan bir Data Lakehouse ve onun üzerinde çalışan, doğal dildeki soruyu
anlayıp analizi kendi planlayan bir *agentic analytics* motoru.

---

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

Böylece 8B'lik bir modelle çalışan sistem, demo gününde daha güçlü modelle daha da iyi çalışır.

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
| `agent-core/tests/golden/` | Golden set: ilerlemenin objektif ölçüsü |
| `agent-core/scripts/` | Geliştirme seed'i, golden koşucusu |
| `lakehouse-core/` | Data Lakehouse — ingestion, Bronze/Silver/Gold, semantic catalog |
| `docs/ARCHITECTURE.md` | **Mimari** — katmanlar, sözleşmeler, agent döngüsü, araçlar, jeneriklik garantileri |
| `docs/adr/` | **Mimari karar kayıtları** — her kararın gerekçesi ve ölçümü |
| `docs/` | Sözleşme dokümanları, açılış toplantısı slaytları |

## Hızlı başlangıç

```bash
cp .env.example .env          # değerleri doldurun — .env asla commit edilmez
ollama pull qwen3:8b          # geliştirme modeli

cd agent-core
uv sync --extra dev              # uv.lock'taki sabit sürümlerle kurar
python scripts/dev_seed.py    # gerçek BDDK verisiyle geliştirme lakehouse'u

uv run python -m kkb_agent.cli --trace "2025'te konut kredisi nasıl değişti?"
uv run python -m kkb_agent.serve          # arayüz: http://127.0.0.1:8765 (ADR-0044)
uv run python scripts/run_golden.py
```

Ayrıntı: [docs/AGENT.md](docs/AGENT.md)

## Veri kaynakları

| Kaynak | Kapsam | Erişim |
|---|---|---|
| BDDK Aylık Bülten | 2021-01 → 2026-06 | Kimlik doğrulaması olmayan JSON endpoint |
| BDDK Haftalık Bülten | aynı | dönem bazlı sorgu |
| BDDK FinTürk (il bazlı) | aynı | il + taraf kırılımlı JSON |
| TCMB EVDS 3 | aynı | `key` header'ı ile REST |
| Ad-hoc URL | demo anında | PDF / Excel / görsel / metin |

Endpoint ayrıntıları ve doğrulanmış tablo haritası:
[docs/LAKEHOUSE_CONTRACT.md](docs/LAKEHOUSE_CONTRACT.md) § 5.

## Çalışma düzeni

- `main` — korumalı. Doğrudan geliştirme yapılmaz.
- `feature/*` — her iş kolu kendi dalında çalışır, tamamlanan görevler buraya push edilir.
- Birleştirme PR üzerinden yapılır.

| Dal | Kapsam |
|---|---|
| `feature/agent-engine` | Agentic analytics motoru, araçlar, golden set |
| `feature/lakehouse` | Ingestion, Bronze/Silver/Gold, semantic catalog |

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
