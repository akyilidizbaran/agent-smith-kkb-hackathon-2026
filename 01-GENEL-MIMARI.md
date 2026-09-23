# 1. Genel mimari

Agent Smith iki bağımsız Python paketinden oluşur. **`lakehouse-core`** sıfırdan yazılmış bir veri gölü evidir (Data
Lakehouse). **`agent-core`** bu havuz üzerinde çalışan agentic analitik motorudur. İki paket arasında kod bağımlılığı yoktur:

- Ajan havuzu yalnız **salt-okunur SQL** ile okur.
- Havuza her yazma işlemi `python -m lakehouse …` komut satırı üzerinden, ayrı bir süreçte yapılır (ADR-0024).

Bu ayrım jürinin "yarın REST API, başka bir veritabanı ya da başka bir alan verirsek ne değişir?" sorusunun cevabıdır:
yeni bir kaynak adaptörü eklenir, orkestrasyon ve doğrulama katmanı değişmez.

## 1.1 Katmanlar

```mermaid
flowchart LR
    subgraph K["Kaynaklar"]
        B1["BDDK Aylık Bülten"]
        B2["BDDK Haftalık Bülten"]
        B3["BDDK FinTürk (81 il)"]
        E1["TCMB EVDS"]
        U["Yüklenen dosya<br/>CSV · XLSX · PDF · görsel"]
        W["Web sayfası / adres"]
    end

    subgraph L["lakehouse-core — Data Lakehouse"]
        RAW["RAW<br/>değişmez ham dosya + sha256"]
        BR["Bronze<br/>Parquet"]
        SV["Silver<br/>silver.fact_observation<br/>(tek uzun tablo)"]
        META["meta.*<br/>seri kataloğu · ilişki grafı<br/>artifact · run"]
        GD["Gold<br/>align · decompose · join<br/>(fonksiyon + 7 tablo)"]
        AH["adhoc.*<br/>taslak seriler"]
    end

    subgraph A["agent-core — Agentic Analytics"]
        AG["AnalyticsAgent<br/>(tek orkestrasyon ajanı)"]
        TL["Araçlar<br/>lakehouse · workspace · gold<br/>analitik · web · kayıt"]
        GR["Doğrulama katmanları<br/>sayı · dönem · kapsam · kanıt"]
        LLM["LLM (Kloudeks)<br/>DeepSeek-V4.1-Flash"]
    end

    UI["Web arayüzü<br/>FastAPI + tek sayfa<br/>canlı adımlar · kanıt zinciri"]

    B1 & B2 & B3 & E1 --> RAW
    RAW --> BR --> SV --> GD
    META --- SV
    U & W --> TL
    TL -- "ingest-file (Architect)" --> AH
    AH -- "promote-draft (onayla)" --> SV
    SV -- "salt-okunur SQL" --> TL
    GD -- "gold-run" --> TL
    AG <--> TL
    AG <--> LLM
    AG --> GR
    UI <--> AG
```

| Katman | Görev | Nerede |
|---|---|---|
| **Kaynak bağlayıcıları** | BDDK (aylık, haftalık, FinTürk) ve EVDS'den çekim | `lakehouse-core/src/lakehouse/connectors/`, `parsers/` |
| **RAW** | Kaynaktan gelen dosya bayt bayt, sha256 ile saklanır; hiç değiştirilmez | `storage/raw.py` → `data/raw/<kaynak>/<tarih>/` |
| **Bronze** | Ayrıştırılmış tablo, Parquet | `storage/parquet.py` → `data/bronze/source_id=…/dataset_id=…/` |
| **Silver** | Tüm kaynaklar tek uzun tabloda: `series_id, observation_date, value, unit, measure_type, quality_flag, artifact_sha256, run_id …` | `silver/`, `models/silver/fact_observation.sql` |
| **Katalog (meta)** | Her serinin anlamı: ad, birim, ölçüm tipi (stok/akım/oran/endeks), toplama kuralı, güven düzeyi, kapsam; seriler arası ilişki grafı | `catalog/series/*.yml` → `meta.series`, `meta.series_relation` |
| **Gold** | Anlamı kurulabilen dönüşümler fonksiyon olarak: frekans hizalama, kümülatiften akıma, dönem üzerinden birleştirme | `gold/` (`align_frequency`, `decompose_cumulative`, `join_on_period`) |
| **Ad-hoc** | Kullanıcının getirdiği veri önce taslak olarak ayrı tabloya yazılır, onaylanınca Silver'a alınır | `adhoc/`, `catalog/promotion.py` |
| **Ajan** | Soruyu anlar, araç seçer, sonucu doğrular ve anlatır | `agent-core/src/kkb_agent/core/agent.py` |
| **Arayüz** | Soru, canlı adım akışı, tablo/grafik, kanıt zinciri, dışa aktarım, sohbet kaydı | `agent-core/src/kkb_agent/web_app.py`, `static/index.html` |

## 1.2 Bir sorunun yolculuğu

```mermaid
sequenceDiagram
    autonumber
    participant K as Kullanıcı (arayüz)
    participant S as Session (web_app)
    participant A as AnalyticsAgent
    participant G as Araç kapısı + doğrulayıcı
    participant T as Araçlar
    participant H as Lakehouse (DuckDB)
    participant M as LLM

    K->>S: soru (+ yüklenen dosya)
    S->>A: ask(soru)
    A->>A: tur niyeti · dönem · takip bağlamı · katalog ön-yükleme
    loop araç turu (bütçeli)
        A->>M: soru + sunulan araç şemaları
        M-->>A: araç çağrısı
        A->>G: şema → SQL guard → referans → politika
        G->>T: çalıştır
        T->>H: salt-okunur SQL / gold-run
        H-->>T: tablo + provenance
        T-->>A: ToolResult (kısa özet, tablo, hata zarfı)
    end
    A->>A: istenen yetenekler tamam mı? (reel, endeks, grafik, analitik, web)
    A->>M: doğrulanmış olgularla anlatım
    M-->>A: taslak cevap
    A->>A: her sayı araç çıktısında mı? dönem doğru mu? nedensellik iddiası var mı?
    A->>A: kanıt zinciri: sayı → hücre → SQL → gözlem → RAW dosya (sha256)
    A-->>S: cevap + tablo + kanıt
    S-->>K: canlı adımlar, cevap, kanıt zinciri, CSV/XLSX/HTML
```

Ayrıntılı karar akışı [`03-agent-karar-ve-gorev-isleme.md`](03-AGENT-KARAR-VE-GOREV-ISLEME.md) belgesindedir.

## 1.3 Tasarım ilkeleri

1. **Harness güçlü, modele en az iş.** Model hesap yapmaz, ham veriyi görmez. Hangi aracın hangi argümanla çağrılacağına
   karar verir ve doğrulanmış sonucu anlatır. Toplama, oran, hizalama, reel değer, endeks ve vade grupları deterministik
   kodda hesaplanır.
2. **Tek ajan + deterministik katmanlar.** Planlayıcı, arayıcı, doğrulayıcı ve anlatıcı ayrı LLM ajanları değildir; tek
   orkestrasyon ajanının mantıksal rolleridir (mentör kararı, 12 Eylül). Doğrulama kuralları kodda durur.
3. **Sayı kanıtsız yazılmaz.** Cevaptaki her sayı bir araç çıktısında bulunmalıdır; bulunmayan sayı taşıyan cümle
   cevaptan çıkarılır (ADR-0027, ADR-0066).
4. **Kaynak sadakati ve erişim sözleşmesi.** Kullanıcının belirttiği kaynağa erişilemezse bu gizlenmez, CAPTCHA ya da bot
   koruması aşılmaz. Durum açıkça söylenir ve seçenek sunulur (ADR-0028, ADR-0111).
5. **Jeneriklik.** Alan bilgisi kodda değil katalogda ve yapılandırmadadır. Havuz boşaltılıp başka bir alanın verisiyle
   kurulabilir (`bootstrap --catalog none`); ajanın alan profili katalogdan türetilir (ADR-0048, ADR-0056).
6. **Her karar kayıtlı.** Mimari kararlar gerekçe ve ölçümle `docs/adr/` altında tutulur (111+ ADR).

## 1.4 Modeller

| Rol | Model | Nerede ayarlanır |
|---|---|---|
| Metin ve araç çağırma | `deepseek-ai/DeepSeek-V4.1-Flash` (Kloudeks, OpenAI uyumlu uç) | `LLM_MODEL`, `LLM_BASE_URL` |
| Embedding (hibrit katalog araması) | `kkbhackathon2026/Qwen3-Embedding-8B` | `EMBEDDING_MODEL` |
| OCR / belge okuma | `kkbhackathon2026/Unlimited-OCR` | `VISION_MODEL` |

Dış LLM servisi kullanılmaz; bütün model çağrıları KKB'nin Kloudeks platformuna gider (ADR-0103). Tek istemci
(`llm/openai_compat.py`) OpenAI uyumlu protokolü konuşur; model yalnız `.env`'den seçilir.

## 1.5 Profiller

| Profil | Ne yapabilir |
|---|---|
| **Analyst** | Havuzu sorgular, analiz eder, dosya/web okur, grafik çizer. Yazma araçları kayıt defterinde hiç yoktur. |
| **Architect** | Analyst'in yapabildikleri + dosyayı havuza taslak seri olarak kaydetme (`ingest_from_url`), kayıtlı kaynaktan eksik dönemi çekme (`ingest_source`), kullanıcı onayıyla kataloğa alma (`promote_draft`), iki adımlı onaylı tam sıfırlama. |

Arayüzün üst çubuğundaki **Analyst | Architect** düğmesi profili tek tıkla değiştirir; sohbet ve tablolar korunur
(ADR-0112).
