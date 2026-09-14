# Data/Lakehouse Bağımsız Denetim Raporu

> **Bu rapor bir denetim çıktısıdır. Hiçbir öneri uygulanmamıştır.**
> Rapor hazırlanırken kaynak kodu, testler, SQL dosyaları, katalog dosyaları, branch yapısı
> ve diğer dokümanlar **değiştirilmemiştir**. Ayrıntı için [§21](#21-sonuç-ve-uygulama-yapılmadığına-dair-not).

---

## 1. Belge kimliği ve kapsam

| Alan | Değer |
|---|---|
| **Rapor tarihi** | 2026-09-10 |
| **Branch** | `feature/lakehouse-integration` |
| **Commit** | `ae22de71dcdd29e8b83e00200be4f8e038759058` (`ae22de7`) |
| **Commit başlığı** | `docs: record source access hardening integration` |
| **Commit tarihi** | 2026-09-09 16:47:39 +0300 |
| **Uzak dal ile senkron** | `origin/feature/lakehouse-integration` ile 0 ileri / 0 geri |
| **Çalışma ağacı** | Temiz (`git status --porcelain` boş) |
| **Test sonucu** | **357 passed**, exit code 0 (`uv run pytest -q`, 1,65 s) |
| **Repo kökü** | `AgentSmithler_WorkSpace/` |
| **Denetlenen proje** | `AgentSmithler_WorkSpace/lakehouse-core/` |

> Branch, commit ve test sayısı rapor **yazım anında yeniden doğrulanmıştır**; denetimin
> başındaki değerlerle aynıdır.

### Kapsam

**Kapsam içi:** Data/Lakehouse katmanı — connector'lar, RAW/Bronze depolama, parser'lar,
metadata katalog, provenance, DuckDB güven sınırı, SQL guard, testler, kurulum
tekrarlanabilirliği ve bu katmanın organizatör beklentileriyle uyumu.

**Kapsam dışı (bilinçli):** Silver katmanı geliştirmesi (Sena'da, denetim anında uzak
dalda mevcut değil), Gold katmanı, agentic motor tasarımı. Agent katmanına yalnızca
**veri platformundan beklenen sözleşmeleri** ve mevcut altyapının agent ekibini bloke edip
etmediğini anlayacak kadar bakılmıştır.

### Bu rapor kimin için

Sena (Silver), Elif (Data/Lakehouse) ve agent ekibi. Teknik terimler ilk geçtikleri yerde
kısaca açıklanmıştır.

---

## 2. Yönetici özeti

*(Bir sayfalık özet — ayrıntı için §9–§11)*

### Temel şu anda hangi seviyede?

**Kaynak → RAW → Bronze ekseni güçlü; Bronze'dan sonrası neredeyse boş.**

Yazılım mühendisliği kalitesi bu yarışma için beklenenin üstündedir: içerik-adresli değişmez
RAW deposu (SHA-256), atomik dosya yazımı, artifact ve istek provenance'ının ayrı tutulması,
kimlik bilgisi (credential) temizleme, iki katmanlı DuckDB güven sınırı, sözcüksel SQL guard
ve — özellikle değerli olarak — **dokümantasyonda kanıt seviyesinin açıkça etiketlenmesi**
(`docs/sources/evds.md`: "bu canlı doğrulandı, bu yalnızca testle doğrulandı, bu hiç
doğrulanmadı"). Bu son madde tek başına jüri karşısında olgunluk sinyalidir.

Buna karşılık veri hattı **Bronze Parquet dosyasında bitmektedir**. Silver yoktur, Gold
yoktur, ve Bronze'u agent'ın sorgulayabileceği yere taşıyan **üretim kodu yoktur**.
Semantic katalogda 4 seri vardır. FinTürk kaynağı hiç yoktur. Çalıştırılabilir tek bir giriş
noktası yoktur; her ingestion elle Python yazılarak test içinde kurulmaktadır.

### Silver geliştirmesi için yeterince sağlam mı?

**Girdi tarafı için evet, çıktı tarafı için hayır.**

Sena'nın Silver'da okuyacağı şey (Bronze Parquet + `meta.series` + provenance alanları) hazır
ve tutarlıdır. Ancak Silver'ın **yazacağı yer tanımlı değildir** ve mevcut güvenlik
sertleştirmesi yüzünden en bariz yol (DuckDB'nin Parquet dosyasını doğrudan okuması)
kapalıdır (§9, D1 — *Yerel deneyle doğrulandı*). Silver bitse bile sonucu agent'ın göreceği
yere indirmek için bugün mevcut olmayan bir katman gerekmektedir.

### En büyük üç güven ve demo riski

1. **EVDS resmî uç noktası hiç canlı çağrılmadı.** API anahtarı yoktur; fixture'lar TCMB'nin
   belgelenmemiş iç uç noktasından alınmıştır. En büyük veri kaynağının gerçek üretim
   transport'u sıfır kez sınanmıştır. (§9, D3)
2. **Bronze → sorgulanabilir DuckDB "son metre" ürünleşmemiştir** ve mevcut sertleştirme
   bunu tek bir dar yola indirmiştir. Silver bitse bile agent veri göremez. (§9, D1)
3. **Sessiz veri kaybı riski.** EVDS istek başına gözlem sınırı için pencereleme kodu yoktur;
   parser bunu fark edip uyarı üretir, fakat pipeline uyarıları hiçbir yere yazmaz. Sistem
   eksik veriyi "başarılı" olarak kaydedebilir. (§9, D2 ve D4)

### Elif'in şu anda yapması gereken en değerli iş

**Yayın (publication) katmanı ve agent SQL yüzeyi** — Silver'ın çıktısını DuckDB'de kalıcı,
sürümlü ve provenance'lı bir tabloya indiren, ayrıca agent ekibinin `LAKEHOUSE_CONTRACT.md`
belgesinde tanımladığı okuma arayüzünü karşılayan katman. Sena'nın dosyalarına dokunmaz,
Sena bitirdiği an bağlanır ve jüri kriteri olan "Güven katmanı: kaynak gösterimi –
izlenebilirlik" tam olarak burada kanıtlanır. Ayrıntı §15.

Yan görev: **EVDS pencereleme** — küçük, çakışmasız, gereksinim düzeyinde sessiz bir hatayı
kapatır.

---

## 3. Kullanılan kaynaklar ve kanıt yöntemi

### 3.1 Kaynak öncelik sırası

> **Yol notu.** Aşağıdaki kaynakların bir kısmı git deposunun **içinde**, bir kısmı ise
> deponun bir üst dizinindeki **çalışma alanında** (`kkb hackathon/`) durmaktadır. Repoyu
> klonlayan biri yalnızca "repo içi" olarak işaretlenenlere erişebilir. Bu yüzden repo
> dışındaki dosyalara göreli bağlantı verilmemiştir. Ayrıntı: §20.6.

**Birincil (organizatörün söyledikleri) — şartname olarak kabul edilmiştir.
Konum: çalışma alanı, repo dışı.**

1. `references/transcripts/KKB_Hackathon_2026_Kick_Off_Tam_Transkript.md` (1040 satır,
   36 dk 10 sn kayıt, zaman damgalı)
2. `references/KKB_Hackathon_2026_Kick_Off_Sunumu.pdf` (31 sayfa)

**İkincil (ekip yorumları ve planları) — şartname olarak kabul EDİLMEMİŞTİR.**

| # | Kaynak | Konum |
|---|---|---|
| 3 | `docs/KKB_Agentic_Data_Analytics_Hackathon_Uctan_Uca_Proje_Rehberi.md` | Çalışma alanı, repo dışı |
| 4 | `docs/lakehouse-nihai-karar.md` | Çalışma alanı, repo dışı |
| 5 | `progress.md` | Çalışma alanı, repo dışı |
| 6 | `LAKEHOUSE_BUILD_PLAN.md` (agent ekibinden veri ekibine yazılmış inşa planı) | Çalışma alanı, repo dışı; bir kopyası `origin/feature/agent-engine` dalında `docs/LAKEHOUSE_BUILD_PLAN.md` olarak |
| 7 | `README.md`, `lakehouse-core/README.md`, `docs/branches/*`, `docs/sources/*`, `docs/team-contract.md`, `docs/catalog-contract.md` | **Repo içi** |

**Asıl teknik kanıt — tamamı repo içi:**

8. `lakehouse-core/src/lakehouse/` altındaki gerçek kaynak kodu (4.133 satır)
9. `lakehouse-core/tests/` (5.106 satır, 357 test) ve `lakehouse-core/tests/fixtures/`
10. `lakehouse-core/sql/bootstrap/*.sql`, `lakehouse-core/catalog/series/*.yml`,
    `lakehouse-core/schemas/fact_observation.yml`
11. Git geçmişi, branch farkları, `origin/feature/agent-engine` dalındaki sözleşme belgeleri

> Bu raporun gövdesinde aksi belirtilmedikçe **tüm dosya yolları `lakehouse-core/` köküne
> göredir**; bu rapor da `lakehouse-core/docs/audits/` altındadır.

### 3.2 Kanıt etiketleri

Bu raporda her dış sistem davranışı ve her kritik iddia aşağıdaki etiketlerden biriyle
işaretlenmiştir. **Etiketsiz cümleler yorumdur, kanıt iddiası değildir.**

| Etiket | Anlamı |
|---|---|
| `Doğrulandı` | Bu denetim sırasında yerel olarak çalıştırılarak veya doğrudan kanıt dosyasından okunarak doğrulandı |
| `Koddan gözlemlendi` | Yalnızca kaynak kodu incelemesinden çıkarıldı; çalıştırılmadı |
| `Yerel deneyle doğrulandı` | Bu denetim sırasında geçici bir scratchpad deneyiyle ölçüldü; deney silindi, prosedürü §20'de |
| `Dokümantasyon iddiası` | Repo içi bir belgenin veya docstring'in iddiasıdır; bu denetimde bağımsız olarak doğrulanmadı |
| `Teyit gerekli` | Doğrulanmamıştır ve karar vermeden önce doğrulanması gerekir |

### 3.3 Yöntem sınırları — bilinçli olarak yapılmayanlar

- **Hiçbir gerçek veri kaynağına canlı istek gönderilmemiştir.** EVDS, BDDK ve TCMB uçlarına
  tek bir HTTP çağrısı yapılmamıştır. API anahtarı kullanılmamıştır.
- **Hiçbir dış sistemin durumu değiştirilmemiştir.**
- Resmî dış dokümantasyon (ör. TCMB EVDS Web Servis Kılavuzu) bu denetimde **indirilmemiştir**;
  ona dayanan repo iddiaları `Dokümantasyon iddiası` veya `Teyit gerekli` olarak işaretlenmiştir.
- Proje dosyalarında **hiçbir değişiklik yapılmamıştır**; testler çalıştırılmış, çalıştırma
  sonrası çalışma ağacının temiz kaldığı doğrulanmıştır.

---

## 4. Başlangıç varsayımlarının doğrulanması

Denetim, verilen bilgileri doğru kabul etmeden Git durumundan doğrulamıştır.

| Varsayım | Sonuç | Kanıt yöntemi |
|---|---|---|
| Branch `feature/lakehouse-integration` | ✅ Doğru | `git rev-parse --abbrev-ref HEAD` — `Doğrulandı` |
| Commit `ae22de7` | ✅ Doğru | `git rev-parse HEAD` → `ae22de71dcdd…` — `Doğrulandı` |
| Origin ile senkron | ✅ 0 ileri / 0 geri | `git rev-list --left-right --count origin/feature/lakehouse-integration...HEAD` — `Doğrulandı` |
| Commit edilmemiş değişiklik | ✅ Yok | `git status --porcelain` boş — `Doğrulandı` |
| Test sayısı 357 | ✅ Doğru | `uv run pytest -q` → `357 passed in 1.65s`, exit 0 — `Doğrulandı` |
| Testlerin proje dosyalarını değiştirmemesi | ✅ Değiştirmiyor | Ön/son snapshot: `data/` boş kaldı, `git status` temiz — `Doğrulandı` |

### 4.1 Raporlanması gereken sapmalar ve ek gözlemler

Bunların hiçbiri düzeltilmemiştir; yalnızca raporlanmaktadır.

**S1 — Üç ek git worktree mevcut, hepsi temiz.** `Doğrulandı`

```
/…/AgentSmithler_WorkSpace                        ae22de7 [feature/lakehouse-integration]
/…/AgentSmithler_WorkSpace-metadata-catalog       ea9d654 [feature/lakehouse-metadata-catalog]
/…/AgentSmithler_WorkSpace-source-hardening       71c08a4 [feature/source-access-hardening]
/private/tmp/agentsmithler-branch-readmes.cwkmbY  ea9d654 [docs/elif-branch-readmes]
```

Sonuncusu `/private/tmp` altındadır. macOS bu dizini temizlerse git worktree metadata'sı
kopuk kalır. Zararsızdır; `git worktree prune` ile temizlenir. **Bu denetimde
temizlenmemiştir** (talimat gereği worktree temizliği yapılmamıştır).

**S2 — `origin/main` lakehouse kodunu içermiyor.** `Doğrulandı`

`origin/main` = `d81d584`. İçeriği yalnızca taslak dokümanlar, agent sözleşme belgeleri ve
açılış slaytı görselleridir. `lakehouse-core/` dizini `main` üzerinde **yoktur**.
Bunun freeze/değerlendirme açısından anlamı için §19-A1'e bakınız.

**S3 — `origin/feature/lakehouse-main-ready` (`db4182a`) integration'dan sapmış.** `Doğrulandı`

`git diff --stat origin/feature/lakehouse-main-ready origin/feature/lakehouse-integration`
→ 33 dosya, 1.213 ekleme / 1.277 silme. Yani "main'e hazır" adını taşıyan dal güncel
integration dalı **değildir**.

**S4 — Silver dalı uzakta mevcut değil.** `Doğrulandı`

`git branch -a` çıktısında Silver'a ait bir dal yoktur. Sena denetim anında henüz push
etmemiştir. Bu, Silver'a dokunmama sınırının kod düzeyinde zaten garanti olduğu anlamına gelir.

**S5 — Agent ekibi belirgin biçimde ilerlemiş.** `Doğrulandı`

`origin/feature/agent-engine` = `e63d063` (2026-09-10 01:32) — çalışan bir harness,
19 adet ADR (mimari karar kaydı), golden test seti ve iki kritik sözleşme belgesi içerir:
`docs/LAKEHOUSE_CONTRACT.md` ve `docs/LAKEHOUSE_BUILD_PLAN.md`. Agent tarafı şu anda
`agent-core/src/kkb_agent/adapters/duckdb_lakehouse.py` adlı **geçici bir stub** ile
çalışmaktadır; dosyanın kendi docstring'i "veri ekibi kendi Lakehouse'unu bitirdiğinde bu
dosyanın yerine kendi adaptörleri gelir" demektedir. `Dokümantasyon iddiası`

**S6 — Testler sırasında oluşan geçici değişiklik yok.** `Doğrulandı`

Test çalıştırmaları `-p no:cacheprovider` ile yapıldığı için pytest cache'i de
değiştirilmemiştir. `lakehouse-core/data/` dizini boş kalmıştır (testler `tmp_path` kullanır).

---

## 5. Organizatör beklentileri izlenebilirlik matrisi

Zaman damgaları `references/transcripts/KKB_Hackathon_2026_Kick_Off_Tam_Transkript.md`
dosyasındandır. Sayfa numaraları `references/KKB_Hackathon_2026_Kick_Off_Sunumu.pdf`
dosyasındandır. Dosya yolları `lakehouse-core/` köküne görelidir.

| # | Beklenti | Birincil kaynak | Repodaki karşılığı | Kanıt | Durum |
|---|---|---|---|---|---|
| 1 | Katmanlı Lakehouse (bronze/silver/gold) kurulacak | Transkript `00:07:28`; Sunum s.7 | Şemalar ve Bronze var; Silver/Gold boş | `sql/bootstrap/001_schemas.sql:1-4`; `models/silver/.gitkeep`, `models/gold/.gitkeep` | **Kısmen** |
| 2 | Platform **jenerik** olmalı; içi boşaltılıp sağlık verisiyle çalışabilmeli | Transkript `00:12:33`, `00:12:55`, `00:31:07` | Sınıf düzeyinde jenerik; kayıt/konfigürasyon katmanı yok | `src/lakehouse/connectors/base.py:10-16`; `tests/integration/test_evds_kfe_source_integration.py` (ikinci seri, yeni sınıf yazılmadan) | **Kısmen** |
| 3 | BDDK haftalık + aylık bülten, 2021 Ocak – 2026 Haziran | Sunum s.8; Transkript `00:09:34`, `00:09:48` | Haftalık + aylık connector/parser var; aralık hiç uçtan uca çekilmedi | `src/lakehouse/connectors/bddk_weekly.py`, `bddk_monthly.py`; `data/` boş | **Kısmen** |
| 4 | **BDDK FinTürk (illere göre)** | Sunum s.8; Transkript `00:09:45` | **Yok.** Tüm repoda tek geçtiği yer bir belge satırı | `docs/sources/bddk_monthly.md:105` | **Eksik** |
| 5 | EVDS serileri, 5 yıllık derinlik | Sunum s.9; Transkript `00:10:44` | Connector + parser var; katalogda 2 seri; pencereleme yok; canlı doğrulama yok | `catalog/series/evds.yml`; `docs/sources/evds.md:5-17` | **Kısmen** |
| 6 | Kümülatif verilerin ayrıştırılması | Sunum s.8 (not); Transkript `00:10:25` | Sözlük düzeyinde modellendi ve doğrulama kuralı yazıldı; dönüşüm kodu yok | `src/lakehouse/catalog/series.py:93`, `:324-337`; `schemas/fact_observation.yml:67-75` | **Kısmen — Silver'a ait** |
| 7 | Farklı frekansların hizalanması | Transkript `00:10:53`, `00:11:02` | Parser tarihi bilinçli olarak ham bırakır; hizalama Silver'a bırakılmış | `src/lakehouse/parsers/evds.py:16-27` | **Eksik — Silver'a ait** |
| 8 | Lakehouse Tool: doğal dil → SQL, join, veri keşfi | Sunum s.10; Transkript `00:14:14`, `00:14:21` | `QueryExecutor` + `sql_guard` var; keşif/katalog arama/provenance zarfı yok; sorgulanacak veri yok | `src/lakehouse/query/executor.py`; `src/lakehouse/tools/__init__.py` (yalnızca docstring) | **Kısmen** |
| 9 | Güven katmanı: kaynak gösterimi – izlenebilirlik – doğruluk kontrolü | Sunum s.7 (alt bant) | Artifact/istek provenance güçlü; sorgu sonucuna taşınmıyor | `src/lakehouse/catalog/artifacts.py:107-174`; `src/lakehouse/query/executor.py:57-64` | **Kısmen** |
| 10 | Hazır/lisanslı bulut Lakehouse yasak; kendi çözümünüz | Transkript `00:23:43`–`00:24:11`, `00:25:05` | Tamamen yerel: DuckDB + Parquet + pandas | `pyproject.toml:6-14` | **Tamamlandı** |
| 11 | Açık kaynak kütüphaneler (pypdf, Pandas, DuckDB, Plotly, LanceDB) | Sunum s.20 | Tüm bağımlılıklar açık kaynak | `pyproject.toml:6-14` | **Tamamlandı** |
| 12 | Python ana geliştirme dili | Sunum s.18; Transkript `00:19:58` | Python 3.12 | `pyproject.toml:5` | **Tamamlandı** |
| 13 | Modüler yapı — "kodları tek tek de bakıyoruz" | Transkript `00:23:17`, `00:31:02`; Sunum s.24 | Katman ayrımı net; ikiz `src/` shim ağacı ve boş paketler kirlilik yaratıyor | `src/connectors/`, `src/parsers/`, `src/storage/`, `src/contracts/`, `src/catalog/__init__.py` (boş) | **Kısmen** |
| 14 | API key'ler repoya girmeyecek; private repoda bile negatif puan | Transkript `00:31:38`–`00:32:07` | `.gitignore`'da `.env`; anahtar yalnızca ortam değişkeninden; hata mesajına sızmıyor; locator ve metadata temizleniyor; git geçmişinde `.env` yok | `.gitignore:12`; `src/lakehouse/connectors/evds.py:194-209`; `src/lakehouse/catalog/artifacts.py:17-75` | **Tamamlandı** |
| 15 | Demo günü çalışan, deploy edilmiş çözüm; verilen girdilerle çıktı | Sunum s.24, s.26; Transkript `00:21:40` | Çalıştırılabilir giriş noktası yok (CLI/servis/`__main__` yok) | `grep 'if __name__\|argparse\|def main' src/` → sonuç yok | **Eksik** |
| 16 | Demo'da prompt içinde URL verilecek (pdf/excel/resim) | Sunum s.13; Transkript `00:13:49` | Data katmanında ad-hoc URL ingestion yok | — | **Eksik / ekip kararı** |
| 17 | Demo'da farklı veri kaynağı yükletilebilir (İMKB vb.) | Transkript `00:18:05` | Sınıf düzeyinde mümkün; konfigürasyonla değil | registry yok | **Kısmen** |
| 18 | Yalnızca Kloudeks LLM; harici LLM API yasak | Transkript `00:21:53`, `00:30:03`; Sunum s.28 | Data katmanında hiç LLM çağrısı yok | `requests` yalnızca kaynak uçlarına | **Tamamlandı** |
| 19 | 20 Eylül freeze; sonrası güncelleme yasak; freeze anı klonlanacak | Transkript `00:22:54`–`00:23:04`; Sunum s.16 | Ana çalışma feature dalında; `main` boş | `git ls-tree origin/main` | **`Teyit gerekli`** — bkz. §19-A1 |

---

## 6. Organizatör gereksinimi / ekip kararı / varsayım ayrımı

Bu ayrım kritiktir: bazı şeyler **yapılmak zorundadır**, bazıları **iyi tercihlerdir** ve
"organizatör istedi" diye savunulmamalıdır.

### 6.1 Organizatörün kesin gereksinimleri

Doğrudan transkriptten veya sunumdan gelen, tartışmaya kapalı maddeler:

- Katmanlı Lakehouse ortamı kurulması (Transkript `00:07:28`; Sunum s.7)
- Platformun **jenerik** olması; içinin boşaltılıp başka bir alanla çalışabilmesi
  (Transkript `00:12:33`, `00:12:55`)
- BDDK haftalık bülten, aylık bülten **ve FinTürk (illere göre)** (Sunum s.8)
- EVDS serileri (Sunum s.9)
- 2021 Ocak – 2026 Haziran veri derinliği (Sunum s.8, s.9)
- Kümülatif verilerin ayrıştırılması (Sunum s.8 notu; Transkript `00:10:25`)
- Frekans hizalaması (Transkript `00:10:53`)
- Agent tool ailesi: Lakehouse, Web Search, Web URL, Anomali, Causality, Change Detection
  (Sunum s.10)
- Güven katmanı: kaynak gösterimi, izlenebilirlik, doğruluk kontrolü (Sunum s.7 alt bant)
- Python ana dil (Sunum s.18); açık kaynak kütüphaneler (Sunum s.20)
- Hazır/lisanslı bulut Lakehouse çözümü **yasak** (Transkript `00:23:43`–`00:24:11`)
- Yalnızca Kloudeks LLM; harici LLM API **yasak** (Transkript `00:21:53`, `00:30:03`)
- API key'lerin private repoda bile bulunmaması (Transkript `00:31:38`)
- Demo günü çalışan çözüm, verilen girdilerle çıktı üretimi (Sunum s.24, s.26)
- Modüler yapı; kodun elle inceleneceği (Transkript `00:23:17`, `00:31:02`)

### 6.2 Ekibin mimari tercihleri (gereksinim değil, savunulabilir)

Bunlar iyi kararlardır ancak **organizatör bunları istemedi**; alternatifleri de meşrudur:

- DuckDB + düz Parquet (DuckLake / Iceberg / Delta yerine) — `progress.md` R bölümü, karar 1
- YAML dosyalarından yüklenen `meta.series` semantic catalog — karar kaydı, `docs/catalog-contract.md`
- İki katmanlı DuckDB güven sınırı (trusted / untrusted) + sözcüksel SQL guard
- RAW'ın içerik-adresli (SHA-256) ve değişmez olması
- `dbt` yerine sade SQL runner — `progress.md` R bölümü, karar 3
- Connector ve parser'ın hiçbir şeyi "düzeltmemesi" (ham değerlerin korunması)
- Gold verisinin DuckDB içine materyalize edilmesi — `progress.md` R bölümü, karar 5

### 6.3 Ekibin kendi koyduğu ek kısıtlar

Bunlar organizatör beklentisi değil, **ekibin kendi disiplinidir** — ve iyi disiplindir:

- Parser'da hiçbir tip/tarih dönüşümü yapılmaması (`src/lakehouse/parsers/evds.py:16-27`)
- `flow_ytd` ölçü tipi için `cumulative_reset` alanının zorunlu olması
  (`src/lakehouse/catalog/series.py:324-334`)
- BDDK haftalıkta `expected_measure_label` / `expected_currency` / `expected_column`
  kimlik alanlarının zorunlu olması (`src/lakehouse/connectors/bddk_weekly.py:104-118`)
- `semantic_confidence` alanıyla emin olunmayan serilerin dürüstçe işaretlenmesi

### 6.4 Bu raporun varsayımları

- Organizatörün "tüm seriler" ifadesinin (Sunum s.9) tam kapsamı belirsizdir; bu rapor bunu
  "demo senaryosunu karşılayacak kadar geniş, doğrulanmış bir alt küme + kataloglanmış
  taslak kayıtlar" olarak yorumlamıştır. `Teyit gerekli`
- Freeze anında jürinin hangi branch'i klonlayacağı belirsizdir. `Teyit gerekli` (§19-A1)

---

## 7. Mevcut Data/Lakehouse sistem haritası

> **Bu bölüm mevcut durumu gösterir, önerilen mimariyi değil.** Öneriler §13 ve §15'tedir.

*Terimler: **RAW** = kaynaktan gelen ham baytlar, hiç dokunulmamış. **Bronze** = ayrıştırılmış
ama yorumlanmamış tablo. **Silver** = temizlenmiş, hizalanmış, birimleri normalize edilmiş.
**Gold** = analize hazır. **Provenance** = bir değerin hangi kaynaktan, hangi istekle, hangi
dosyadan geldiğinin kaydı. **Artifact** = diske yazılmış tek bir ham yanıt dosyası.*

```
   EVDS (TCMB)               BDDK Aylık            BDDK Haftalık          FinTürk
        │                         │                       │                  ✗
        ▼                         ▼                       ▼               (YOK)
  EvdsConnector         BddkMonthlyConnector    BddkWeeklyConnector
        └────────────┬────────────┴───────────────────────┘
                     ▼
            RawStorage  →  data/raw/{source_id}/{fetch_date}/{sha256}.{ext}
                     │       (değişmez, içerik-adresli, atomik yazım, dedup)
                     ▼
            FetchedAsset (sha256, fetched_at, http_status, request metadata)
                     │
      ┌──────────────┼───────────────────────────┐
      ▼              ▼                           ▼
ArtifactRepository   EvdsParser / BddkMonthlyParser / BddkWeeklyParser
 meta.artifact       (ağ erişimi yok; yalnızca diskteki artifact'ı okur)
 meta.artifact_request        │
      │                       ▼
      │              ParsedBatch  ──►  warnings  ✗ HİÇBİR YERE YAZILMIYOR
      │                       │
      │                       ▼
      │             ParquetStorage → data/bronze/source_id=…/dataset_id=…/
      │                               schema_version_sha256=…/artifact_sha256=….parquet
      │
      ▼
  DuckDB (yalnızca meta.* şeması dolu)
      │                    ╔══════════════════════════════════════════════╗
      │                    ║  ⚠  KOPUK HALKA                              ║
connect_untrusted()  ◀─────╢  Bronze Parquet'i DuckDB'ye taşıyan          ║
(read-only, hardened,      ║  ÜRETİM KODU YOK                             ║
 lock_configuration)       ║  (yalnızca bir entegrasyon testinde,         ║
      │                    ║   elle yazılmış SQL ile bir kez yapılmış)    ║
      ▼                    ╚══════════════════════════════════════════════╝
QueryExecutor + sql_guard  →  bugün yalnızca meta.* tablolarını görebiliyor
      │
      ▼
  [Agent yüzeyi: YOK]      ← agent ekibi kendi geçici stub'ıyla çalışıyor
```

### 7.1 Gerçekten çalışan uçtan uca akışlar

`Doğrulandı` (testlerle, çevrimdışı):

- **RAW → Bronze, EVDS:** `tests/integration/test_evds_kfe_source_integration.py` ve
  `test_phase_1b_source_integration.py` — fixture baytları → RAW → artifact kaydı →
  parser → Bronze Parquet.
- **RAW → Bronze, BDDK Haftalık:** `tests/integration/test_bddk_weekly_source_integration.py`
- **RAW → Bronze → DuckDB → guarded SELECT:** `tests/integration/test_infrastructure_vertical_slice.py`
  — **ama bu akış üretim kodunda değil, testin kendi içinde elle kurulmuştur**
  (`:53-57`: `register_local_parquet` ardından elle yazılmış `CREATE TABLE bronze.fixture AS …`).
- **Semantic katalog yükleme:** `tests/integration/test_series_catalog_bootstrap.py` — YAML →
  doğrulama → tek transaction → `meta.series`, idempotent.

### 7.2 Yalnızca fixture ile test edilen (sahte HTTP)

`Doğrulandı`: tüm connector testleri in-process sahte session kullanır; hiçbiri socket açmaz.
Bu **bilinçli ve her test dosyasının docstring'inde açıkça yazılıdır** — bir kusur değil,
bir yöntem tercihidir. Ancak sonuç şudur: **connector'ların HTTP davranışının tamamı canlı
olarak doğrulanmamıştır.**

Fixture'lar küçüktür: `tests/fixtures/raw/` altındaki dosyalar 54 bayt ile 3.731 bayt
arasındadır; en büyük EVDS fixture'ı 1.805 bayttır. Gerçek 5 yıllık bir yanıt hiç
ayrıştırılmamıştır. `Doğrulandı`

### 7.3 Canlı doğrulaması eksik olanlar

| Konu | Durum |
|---|---|
| EVDS resmî keyed uç noktası | Hiç çağrılmadı — `Doğrulandı` (`docs/sources/evds.md:17`) |
| EVDS URL biçimi | Hiç ölçülmedi — `Teyit gerekli` (§9, D3) |
| EVDS gözlem sınırı davranışı | Repo belgesine göre 1000 — `Dokümantasyon iddiası` (§9, D4) |
| BDDK aylık/haftalık uçları | Docstring'de "2026-09-08/09 tarihinde canlı doğrulandı" — `Dokümantasyon iddiası` |
| BDDK TLS zinciri | Docstring'de ara sertifika eksikliği iddiası — `Dokümantasyon iddiası` (§10, D8) |
| 5 yıllık tam çekim | Hiç yapılmadı — `Doğrulandı` (`data/` boş) |

---

## 8. Bileşen bazında gerçekleşme durumu

| Bileşen | Görevi | Gerçekten çalışan kısım | Yalnızca test edilen kısım | Canlı doğrulaması eksik | Sahibi / dal |
|---|---|---|---|---|---|
| `EvdsConnector` | EVDS'den ham bayt çekip RAW'a yazar | Retry sınıflaması, anahtar okuma, URL kurma, RAW yazımı | Tüm HTTP davranışı (sahte session) | Resmî keyed uç hiç çağrılmadı; URL biçimi ölçülmedi; pencereleme yok | Elif / `lakehouse-source-access` |
| `BddkMonthlyConnector` | Aylık bülten JSON ucu | Form kurma, tek `kalemSutun` kuralı, TLS hata sınıflaması | HTTP davranışı | TLS ara sertifika sorunu için repoda çözüm yok | Elif / `lakehouse-source-access` |
| `BddkWeeklyConnector` | Haftalık bülten JSON ucu | Konumsal `id` + `expected_*` kimlik doğrulaması | HTTP davranışı | Aynı TLS sorunu | Elif / `source-access-bddk-weekly` |
| `RawStorage` | Değişmez, içerik-adresli RAW deposu | Tamamı: dedup, atomik yazım, çakışma tespiti | — | Büyük hacimde tarama maliyeti ölçülmedi | Elif / `infrastructure` |
| `ArtifactRepository` | `meta.artifact` + `meta.artifact_request` | Tamamı: kimlik bilgisi temizleme, değişmezlik kontrolü | — | — | Elif / `infrastructure` |
| `EvdsParser` / `BddkMonthlyParser` / `BddkWeeklyParser` | RAW → uzun format DataFrame | Ayrıştırma, null koruma, uyarı üretimi, kimlik doğrulama | Fixture'lar 3–5 satırlık minik örnekler | Gerçek 5 yıllık yanıt hiç ayrıştırılmadı | Elif |
| `ParquetStorage` | Bronze Parquet + gömülü provenance | Yazma, kimlik gömme/okuma, mutasyon reddi | `register_local_parquet` yalnızca 3 testte | — | Elif / `infrastructure` |
| `IngestionPipeline` | Connector→artifact→parser→Bronze | Akış ve kimlik tutarlılık kontrolleri | — | `warnings` düşürülüyor; `meta.run` yazılmıyor | Elif |
| `meta.series` katalog yükleyici | Serilerin anlamı (birim, ölçü tipi, aliases) | Hepsi-veya-hiç doğrulama, tek transaction, idempotent içerik hash'i | — | İçerik yalnızca 4 seri | Elif / `metadata-catalog` |
| `connect_trusted` / `connect_untrusted` | İki katmanlı güven sınırı | Tamamı; ayar adları runtime kataloğundan doğrulanıyor | — | Sertleştirmenin yan etkisi ürünleşmemiş (§9, D1) | Elif / `source-access-hardening` |
| `sql_guard` + `QueryExecutor` | Agent SQL'ini sınırlama | Tokenizer, allowlist, satır sınırı, bağlantı profili doğrulaması | — | Sorgulanacak gerçek veri yok | Elif |
| `meta.run`, `meta.dataset_version`, `meta.source` | Çalıştırma ve sürüm kaydı | **Hiçbiri** — tablo var, yazan/okuyan üretim kodu yok | Yalnızca "tablo mevcut mu" testi | — | Sahipsiz |
| Silver | Temizleme, hizalama, normalizasyon | Yok | — | — | **Sena** (uzakta henüz yok) |
| Gold / agent yüzeyi | Analize hazır katman + okuma arayüzü | Yok | — | — | Sahipsiz |

---

## Bulgular hakkında — öncelik ve sınıflandırma anahtarı

### Öncelik seviyeleri

| Seviye | Anlamı |
|---|---|
| **P0** | Yarışma sonucunu doğrudan etkiler. Freeze'e kadar çözülmezse demo başarısız olabilir veya jüriye yanlış veri gösterilebilir. |
| **P1** | Ciddi eksik veya risk. Demo'yu tek başına düşürmez ama puan kaybettirir ya da geç fark edilirse pahalı olur. |
| **P2** | Kalite, bakım ve jüri algısı. Düzeltilmesi ucuz, düzeltilmemesi ölümcül değil. |

### Bulgu sınıfı (bir bulgu her zaman "hata" değildir)

| Sınıf | Anlamı |
|---|---|
| **Hata** | Kod yanlış davranıyor veya sessizce yanlış sonuç üretebiliyor. |
| **Planlanmış eksik** | Ekip bilinçli olarak sonraya bıraktı; kusur değil, henüz yapılmamış iş. Risk, planın gerçekleşip gerçekleşmeyeceğidir. |
| **Silver'a ait beklenen iş** | Bu katmanın görevi değil; Sena'nın kapsamında. Data/Lakehouse tarafında "eksik" sayılmamalı. |
| **Süreç/koordinasyon** | Kodla değil, ekip çalışma düzeniyle ilgili. |

Her bulguda ayrıca **Silver'dan bağımsızlık** ve **Sena ile çakışma ihtimali** belirtilmiştir.

---

## 9. P0 bulguları

### D1 — Bronze → sorgulanabilir DuckDB "son metre" ürünleşmemiş; sertleştirme bunu tek bir dar yola indiriyor

**Sınıf:** Planlanmış eksik + koda gömülü, belgelenmemiş bir tuzak
**Alan:** Doğruluk · Demo güvenilirliği · Operasyonel dayanıklılık

**Somut durum.** `apply_runtime_security` fonksiyonu **her** DuckDB bağlantısına — trusted
olan dahil — `enable_external_access = false` uygular:

- `src/lakehouse/db/connection.py:38-55` — fonksiyonun kendisi
- `src/lakehouse/db/connection.py:93` — `_open()` içinden her bağlantıda çağrılıyor
- `src/lakehouse/db/connection.py:100-114` — `connect_trusted` da bu `_open`'ı kullanıyor

**Yerel deneyle doğrulandı** (prosedür §20.3):

1. `enable_external_access = false` iken `read_parquet('…')` çağrısı
   `PermissionException: … file system operations are disabled by configuration` ile
   reddediliyor. Yani `CREATE TABLE … AS SELECT * FROM read_parquet(…)` ve `COPY` yolları
   **trusted bağlantıda dahi kapalı**.
2. Ayarı geri açmak **mümkün değil**: `SET enable_external_access = true` →
   `InvalidInputException: Cannot enable external access while database is running`.
   Yani bu tek yönlü bir kapıdır.
3. **Çalışan tek yol:** Python tarafında Parquet okunur → `connection.register()` ile
   bellekteki ilişki kaydedilir → `CREATE TABLE … AS SELECT * FROM <kayıtlı_ilişki>` ile
   kalıcılaştırılır. Bu yol çalışmaktadır.
4. **Sessiz tuzak:** Kayıtlı ilişki üzerine `CREATE VIEW` **başarıyla oluşur ve diske
   yazılır**, ancak sonraki bağlantıda okunmaya çalışıldığında
   `CatalogException: Table with name rel does not exist` ile patlar. Kayıtlı ilişki
   oturum ömürlüdür; view kalıcıdır. Bu, yazarken hata vermeyen, demo günü patlayan bir
   zaman bombasıdır.

**Ürünleşme durumu.** Bu materyalizasyon adımı üretim kodunda **yoktur**.
`ParquetStorage.register_local_parquet` (`src/lakehouse/storage/parquet.py:126-140`) bir adım
öncesinde durur: kaydeder, materyalize etmez. Tam akış yalnızca bir entegrasyon testinde,
elle yazılmış SQL ile bir kez gösterilmiştir:
`tests/integration/test_infrastructure_vertical_slice.py:53-57`. `Doğrulandı`

**İlgili organizatör beklentisi.** §5 #1, #8, #15 — "Lakehouse aracı … bu datayı retrieve
edebilmeli … joinleyebilmeli" (Transkript `00:14:14`–`00:14:29`).

**Gerçek etkisi.** Sena Silver'ı bitirse bile sonucu agent'ın göreceği yere indiren bir
mekanizma yoktur. `connect_untrusted` ile açılan salt-okunur bağlantı bugün yalnızca
`meta.*` tablolarını görebilmektedir.

| Öncelik | Silver'dan bağımsız | Sena ile çakışma | Tahmini büyüklük |
|---|---|---|---|
| **P0** | ✅ Tamamen | Düşük (`db/`, `storage/`, `query/`, yeni `publish/`) | Orta (≈300–400 satır + testler) |

**Düzeltmeyi kanıtlayacak test.** Bir Bronze Parquet dosyasının materyalize edilip
`connect_untrusted` + `QueryExecutor` üzerinden doğru satırlarla okunabildiğini gösteren
uçtan uca entegrasyon testi; ayrıca "kayıtlı ilişki üzerine oluşturulan view sonraki
bağlantıda okunamaz" regresyon testi.

---

### D2 — Parser uyarıları sessizce kayboluyor

**Sınıf:** Hata (bilgi kaybı) — planlanmış eksik değil, çünkü uyarılar zaten üretiliyor
**Alan:** Veri bütünlüğü · Gözlemlenebilirlik · Hata yönetimi

**Somut durum.** Parser'lar gerçekten değerli uyarılar üretmektedir:

- "gözlem sayısı istek başına limite ulaştı; yanıt sessizce kırpılmış olabilir"
  (`src/lakehouse/parsers/evds.py:241-247`)
- "`totalCount` ile dönen gözlem sayısı uyuşmuyor" (`src/lakehouse/parsers/evds.py:235-239`)
- "66 dönem istendi, 5 döndü" (`tests/parsers/test_bddk_monthly_parser.py:136`)
- "`defaultValue` ölçülmüş bir sıfır sayılmamalı" (`tests/parsers/test_bddk_monthly_parser.py:127-128`)
- "`series_id` alt çizgi → nokta dönüşümüyle türetildi" (`src/lakehouse/parsers/evds.py:155-160`)

`IngestionPipeline.run` bu uyarıları `ParsedBatch` içinde alır
(`src/lakehouse/ingestion/pipeline.py:54`), `IngestionResult`'a taşır
(`:58-64`) ve **hiçbir yere yazmaz** — ne log, ne `meta.*` tablosu, ne dosya.

**Doğrulama.** `grep -rn '\.warnings' src/ tests/` çıktısında **üretim kodunda tek bir
tüketici yoktur**; yalnızca test dosyaları uyarıları kontrol eder. `Doğrulandı`

**İlgili organizatör beklentisi.** §5 #9 — "Güven katmanı: … Doğruluk Kontrolü" (Sunum s.7).

**Gerçek etkisi.** Sistem bozuk veya eksik veriyi "başarılı" olarak kaydeder. Jüri "veriyi
nasıl doğruluyorsunuz" diye sorduğunda gösterilebilecek çalışan bir mekanizma yoktur.
D4 ile birleştiğinde sessiz veri kaybı zinciri tamamlanır.

| Öncelik | Silver'dan bağımsız | Sena ile çakışma | Tahmini büyüklük |
|---|---|---|---|
| **P0** | ✅ Tamamen | Düşük (`pipeline.py` Bronze ingestion'a ait) | Küçük (≈100 satır + bir meta tablo) |

**Düzeltmeyi kanıtlayacak test.** Kırpılmış bir EVDS fixture'ı ingest edildiğinde uyarı
kaydının kalıcı bir tabloda göründüğünü ve çalıştırma durumunun `success` olmadığını
doğrulayan test.

---

### D3 — EVDS resmî uç noktası hiç canlı çağrılmadı; URL biçimi doğrulanmadı

**Sınıf:** Planlanmış eksik (dış bağımlılık nedeniyle) — ama etkisi P0
**Alan:** Doğruluk · Demo güvenilirliği · Dış bağımlılık

**Somut durum.** Ekibin kendi belgesi bunu açıkça yazmaktadır (`docs/sources/evds.md:5-17`):

> "Official keyed endpoint, live — **NOT VERIFIED**. No API key was available. The keyed
> endpoint has never been called by this track." (`docs/sources/evds.md:17`)

Fixture'lar TCMB EVDS web uygulamasının **belgelenmemiş iç uç noktasından**
(`POST /igmevdsms-dis/fe`) alınmıştır (`docs/sources/evds.md:16`, `:21`). Belge bunun
üretim transport'u olarak kullanılmaması gerektiğini de yazmaktadır. `Doğrulandı`
(belge okunarak)

**URL biçimi — `Teyit gerekli`.** `EvdsConnector._build_url`
(`src/lakehouse/connectors/evds.py:161-192`) URL'yi şöyle kurar
(`:191`: `base = f"{self._base_url}/{parts[0]}"`):

```
https://evds3.tcmb.gov.tr/igmevdsms-dis/series=TP.KFE.TR&startDate=01-01-2026&endDate=30-06-2026&type=json
```

Dikkat: **soru işareti yoktur**; `series=…` bir sorgu parametresi değil, bir **yol parçası**
olarak eklenmektedir. Bu, eski EVDS2 servisinin bilinen biçimiyle uyumlu görünmektedir,
ancak **bu denetimde ölçülmemiştir** ve resmî dokümantasyon bu denetim kapsamında
indirilmemiştir. Repo `evds3` tabanının doğru olduğunu ve `evds2` yolunun 302 ile
yönlendirdiğini iddia etmektedir (`docs/sources/evds.md:14`) — bu bir
`Dokümantasyon iddiası`dır.

**Gerçek etkisi.** Demo günü ilk gerçek EVDS çağrısında HTTP 400/404 alınması ihtimali
vardır ve yedek yol yoktur. Bu, projedeki **tek en büyük tekil risktir**.

| Öncelik | Silver'dan bağımsız | Sena ile çakışma | Tahmini büyüklük |
|---|---|---|---|
| **P0** | ✅ Tamamen | Yok | Kod açısından çok küçük — **ama API anahtarı bir dış bağımlılıktır** |

**Düzeltmeyi kanıtlayacak test.** `docs/sources/evds.md:39-58` içinde zaten yazılı olan
5 adımlı smoke prosedürü: tek seri, kısa aralık, HTTP 200, zarf alanlarının fixture ile
karşılaştırılması, gözlem sayısının beklenenle eşleşmesi. Sonrasında fixture'ların
keyed-uç yakalamasıyla değiştirilmesi.

**Not:** Bu bir kod işi değil, **tedarik işidir**. EVDS API anahtarı başvurusu geciktikçe
tüm EVDS hattı spekülatif kalır. Bkz. §19-A2.

---

### D4 — EVDS gözlem sınırı için pencereleme yok; sessiz veri kaybı riski

**Sınıf:** Hata (gereksinim düzeyinde eksik davranış)
**Alan:** Veri bütünlüğü · Doğruluk

**Somut durum.** Repo, EVDS'in tek istekte en fazla 1000 gözlem döndürdüğünü ve fazlasını
`endDate`'ten geriye doğru **sessizce kırptığını** belgelemektedir:

- `src/lakehouse/connectors/evds.py:11-12` (docstring): "A single request returns at most
  1000 observations, counted backwards from `endDate`. Larger ranges are silently truncated,
  so the caller must window its requests."
- `src/lakehouse/connectors/evds.py:38` — `EVDS_OBSERVATION_LIMIT = 1000` sabiti tanımlı ve
  yalnızca metadata'ya yazılıyor (`:276`)

**Bu sınırın kendisi bir `Dokümantasyon iddiası`dır** — TCMB kılavuzuna dayandığı belirtilmiş,
bu denetimde bağımsız olarak doğrulanmamıştır.

**Pencereleme kodu yoktur.** `grep -rni 'window|chunk|paginat|split_range' src/` çıktısında
yalnızca **yorum satırları** çıkmaktadır; uygulama yoktur. `Doğrulandı`

Parser durumu fark eder ve uyarı üretir
(`src/lakehouse/parsers/evds.py:241-247`) — ancak D2 gereği bu uyarı hiçbir yere yazılmaz.

**Ölçek.** Organizatör 2021 Ocak – 2026 Haziran aralığını istemektedir (Sunum s.9). Bu
yaklaşık 5,5 yıldır. Günlük frekanslı bir seride bu ≈1.400 gözlem, haftalıkta ≈285 gözlem
eder. Yani **günlük serilerde sınır aşılır**. (Bu aritmetik bir çıkarımdır; gerçek gözlem
sayısı seriye göre değişir. `Koddan gözlemlendi` + hesap)

**Gerçek etkisi.** Günlük serilerde en eski dönemler (2021–2022) sessizce eksik gelir.
Jüri "2021'den beri" diye sorduğunda yanlış bir cevap üretilir ve hiçbir katman bunu
bildirmez.

| Öncelik | Silver'dan bağımsız | Sena ile çakışma | Tahmini büyüklük |
|---|---|---|---|
| **P0** | ✅ Tamamen | Yok (`connectors/evds.py` Elif'in dosyası) | Küçük (≈80–120 satır) |

**Düzeltmeyi kanıtlayacak test.** Sınırı aşan gözlem sayısına sahip bir fixture ile birden
fazla pencere isteği yapıldığını, her pencerenin ayrı RAW artifact olarak indiğini ve
birleşik gözlem sayısının beklenenle eşleştiğini doğrulayan test; eşleşmezse
`OBSERVATION_COUNT_MISMATCH` yükseltilmesi.

---

## 10. P1 bulguları

### D5 — `meta.run`, `meta.dataset_version`, `meta.source` tabloları ölü

**Sınıf:** Planlanmış eksik — ama "provenance var" yanılsaması yarattığı için riskli
**Alan:** Provenance ve sürümleme

Üç tablo da `sql/bootstrap/002_meta_tables.sql` içinde tanımlıdır (`:1`, `:21`, `:31`).
**Hiçbir üretim kodu bu tablolara yazmaz veya bunlardan okumaz.** `Doğrulandı`
(`grep -rn 'meta\.run|dataset_version|meta\.source' src/` → yalnızca bir docstring atfı,
`src/lakehouse/catalog/series.py:4`).

`new_run_id()` üretilebilmektedir (`src/lakehouse/contracts/identifiers.py:67-70`) ancak
**hiçbir yerde kullanılmamaktadır** — `grep -rn 'run_id' src/` çıktısında yalnızca
`identifiers.py` görünür. `Doğrulandı`

`tests/infrastructure/test_db.py:30` yalnızca tabloların **var olduğunu** doğrular. Bu,
"provenance altyapısı çalışıyor" izlenimi veren bir yanlış güven kaynağıdır.

**Sürümleme ve yeniden çalıştırma güvenliği hakkında dürüst değerlendirme:** Artifact
düzeyinde SHA-256 tabanlı tekilleştirme **gerçekten çalışmaktadır ve iyi tasarlanmıştır** —
aynı baytlar iki kez çekilirse tek dosya tutulur, `last_seen_at` güncellenir, farklı
metadata ile aynı hash reddedilir (`src/lakehouse/catalog/artifacts.py:125-141`;
`src/lakehouse/storage/raw.py:126-136`). Ancak **dataset düzeyinde vintage/sürüm kaydı
yoktur**. "Kaynak 2021 Mart rakamını revize etti" durumunu sistem göremez. Organizatörün
BDDK notu (Sunum s.8: kümülatif ve revize edilen veriler) tam da bunu gerektirmektedir.

| Öncelik | Silver'dan bağımsız | Sena ile çakışma | Büyüklük | Kanıt testi |
|---|---|---|---|---|
| **P1** | ✅ | Düşük–orta (`meta.*` ortak alan) | Orta | Aynı dataset'in iki farklı vintage'ının ayrı satır olarak kaydedilmesi ve `is_current` bayrağının doğru dönmesi |

---

### D6 — Çalıştırılabilir giriş noktası ve kaynak registry'si yok

**Sınıf:** Planlanmış eksik
**Alan:** Genericlik · Bakım kolaylığı · Demo güvenilirliği

`grep -rn 'if __name__|argparse|click|typer|def main' src/` → **sonuç yok**. `Doğrulandı`
`dataset_id → (connector, parser, parametreler)` eşlemesi de yoktur; registry araması boş
dönmektedir. `Doğrulandı`

Sonuç: her ingestion elle Python yazılarak, test içinde kurulmaktadır.

**Jeneriklik iddiası üzerine dürüst değerlendirme.** Sınıf düzeyinde jeneriklik **gerçektir
ve kanıtlıdır**: `tests/integration/test_evds_kfe_source_integration.py` ikinci bir EVDS
serisinin **yeni bir connector/parser sınıfı yazılmadan** Bronze'a ulaştığını gösterir ve
testin docstring'i bunu açıkça amaç edinmiştir. Ancak **konfigürasyon düzeyinde jeneriklik
yoktur**: yeni bir kaynak eklemek hâlâ Python yazmayı gerektirir. Organizatör "içini
boşaltıp bambaşka bir sağlık verisiyle de çalışabilir halde olması gerekiyor"
(Transkript `00:12:33`) dediğinde gösterilecek şey bir konfigürasyon dosyası değil, bir
commit olur.

| Öncelik | Silver'dan bağımsız | Sena ile çakışma | Büyüklük | Kanıt testi |
|---|---|---|---|---|
| **P1** | ✅ | Düşük | Orta | Bir YAML dataset tanımından ingestion'ın uçtan uca çalıştığı test |

---

### D7 — Semantic katalog kapsamı 4 seri; FinTürk kaynağı hiç yok

**Sınıf:** Planlanmış eksik (katalog) + kapsam eksiği (FinTürk)
**Alan:** Genericlik · İşlevsellik

`catalog/series/*.yml` içeriği `Doğrulandı`: EVDS 2 seri, BDDK aylık 1 seri, BDDK haftalık
1 seri — toplam **4**.

Organizatör EVDS'de "Seriler içerisindeki tüm veriler" (Sunum s.9), BDDK'da haftalık + aylık
+ **FinTürk – İllere Göre** (Sunum s.8) istemektedir.

**FinTürk için ne connector, ne parser, ne katalog kaydı vardır.** Tüm repoda tek geçtiği
yer bir belge satırıdır: `docs/sources/bddk_monthly.md:105`. `Doğrulandı`

Not: Katalog **yükleyicisi** çok iyidir (hepsi-veya-hiç doğrulama, tek transaction,
idempotent içerik hash'i, `first_obs`/`last_obs` alanlarına dokunmama disiplini —
`src/lakehouse/catalog/series.py`). Eksik olan **kod değil, içeriktir**.

| Öncelik | Silver'dan bağımsız | Sena ile çakışma | Büyüklük | Kanıt testi |
|---|---|---|---|---|
| **P1** | ✅ | Yok | FinTürk: orta–büyük · Katalog içeriği: içerik işi | FinTürk için: fixture tabanlı connector/parser testleri |

---

### D8 — BDDK TLS ara sertifika sorunu için repoda çalışan çözüm yok

**Sınıf:** Planlanmış eksik — kodun tepkisi doğru, dağıtım tarafı eksik
**Alan:** Operasyonel dayanıklılık · Demo güvenilirliği

Connector docstring'leri `www.bddk.org.tr` sunucusunun yalnızca leaf sertifikasını
gönderdiğini ve `GlobalSign RSA OV SSL CA 2018` ara sertifikasını atladığını, dolayısıyla
doğru yapılandırılmış bir istemcinin doğrulamada başarısız olacağını iddia etmektedir
(`src/lakehouse/connectors/bddk_monthly.py:22-27`;
`src/lakehouse/connectors/bddk_weekly.py:48-56`). **Bu bir `Dokümantasyon iddiası`dır**;
bu denetimde canlı olarak doğrulanmamıştır.

**Kodun tepkisi doğrudur ve övgüye değerdir.** TLS asla zayıflatılmamaktadır: `verify=False`
kullanımı yoktur ve bir test bunu **kaynak kodu metni üzerinden** ayrıca kontrol etmektedir
(`tests/connectors/test_bddk_monthly_connector.py:428`). SSL hatası
`SOURCE_UNAVAILABLE` + `retryable=False` olarak sınıflandırılır
(`src/lakehouse/connectors/bddk_monthly.py:244-256`). Bu, jüri güvenlik değerlendirmesi
açısından olumlu bir sinyaldir.

**Eksik olan:** Repoda ne bir CA bundle, ne dokümante edilmiş bir kurulum adımı, ne de
doğrulanmış bir `requests.Session` fabrikası vardır. `grep -rn 'REQUESTS_CA_BUNDLE|certifi|ca_bundle' src/ docs/`
→ sonuç yok. `Doğrulandı`

**Sonuç:** İddia doğruysa, temiz bir makinede BDDK çekimi başarısız olur ve bunu çözmenin
belgelenmiş bir yolu yoktur.

| Öncelik | Silver'dan bağımsız | Sena ile çakışma | Büyüklük | Kanıt testi |
|---|---|---|---|---|
| **P1** | ✅ | Yok | Küçük | Enjekte edilen `Session` ile doğrulama açıkken başarılı bağlantı kurulduğunu gösteren belgelenmiş prosedür |

---

### D9 — Sürekli entegrasyon (CI) yok

**Sınıf:** Süreç/koordinasyon
**Alan:** Tekrar üretilebilirlik

`AgentSmithler_WorkSpace/.github` dizini **yoktur**. `Doğrulandı`
357 test yalnızca elle çalıştırılmaktadır. Freeze'e 10 gün vardır (Sunum s.16: 20 Eylül) ve
üç kişi paralel dallarda çalışmaktadır.

| Öncelik | Silver'dan bağımsız | Sena ile çakışma | Büyüklük | Kanıt testi |
|---|---|---|---|---|
| **P1** | ✅ | Yok | Çok küçük (≈40 satırlık workflow) | Workflow'un push'ta `make test` çalıştırıp yeşil dönmesi |

---

## 11. P2 bulguları

### D10 — İkiz `src/` shim ağacı ve boş paketler

**Sınıf:** Planlanmış eksik (geçiş dönemi kalıntısı) — `Doğrulandı`
**Alan:** Bakım kolaylığı · Jüri değeri

`src/connectors/`, `src/parsers/`, `src/storage/`, `src/contracts/`, `src/pipelines/`,
`src/quality/`, `src/utils/` yalnızca geriye dönük uyumluluk için import shim'i içerir
(örn. `src/parsers/base.py` yalnızca `from src.lakehouse.parsers.base import BaseParser`).
`src/catalog/__init__.py` **tamamen boştur**. Ayrıca `src/lakehouse/` altında dört adet boş
"reserved" paket vardır: `provenance`, `quality`, `semantics`, `tools` — her biri yalnızca
bir docstring içerir.

`lakehouse-core/README.md` bu durumu açıklamaktadır, yani gizlenmiş değildir. Ancak
organizatör "kodları tek tek de bakıyoruz" ve "modüler yapıyı çok önemsiyoruz"
(Transkript `00:23:17`, `00:31:02`) demiştir. İki paralel paket ağacı ilk bakışta
modülerlik değil, tamamlanmamış bir refactor izlenimi verebilir.

**Dikkat:** Shim'leri silmek Sena'nın import'larını kırabilir. Bu yüzden §18'de
"ekip kararı bekle" başlığındadır.

| Öncelik | Silver'dan bağımsız | Sena ile çakışma | Büyüklük |
|---|---|---|---|
| **P2** | Kısmen | **Orta–yüksek** (import kırma riski) | Çok küçük |

---

### D11 — `progress.md` ciddi biçimde bayat

**Sınıf:** Süreç/koordinasyon — `Doğrulandı`
**Alan:** Tekrar üretilebilirlik · Ekip koordinasyonu

`progress.md` P bölümü hâlâ `5f0e47f` commit'indeki base kurulumunu "güncel iş" olarak
göstermekte ve "22 test" referansı vermektedir. Repo ise `ae22de7`'dedir; connector,
parser, katalog ve güvenlik çalışmaları tamamlanmış, test sayısı 357'ye çıkmıştır.
Q bölümündeki tek bloker çözülmüş durumdadır.

Üç kişilik bir ekipte bu gerçek bir koordinasyon riskidir. **Bu, tek bir kişinin değil,
ekibin güncellemesi gereken bir belgedir.**

---

### D12 — İki farklı kurulum yolu, biri sabitlenmemiş

**Sınıf:** Planlanmış eksik (geçiş dönemi) — `Doğrulandı`
**Alan:** Tekrar üretilebilirlik

`uv.lock` doğru ve günceldir: `uv lock --check` temiz döner, 21 sabit sürüm içerir,
`requires-python = "==3.12.*"` kısıtı vardır.

Buna karşılık `requirements.txt` tamamen sabitsizdir (`pandas`, `pyarrow`, `duckdb`,
`requests`, `pyyaml`, `pytest` — sürüm yok). `.python-version` dosyası yoktur, ancak
`pyproject.toml:5` (`>=3.12,<3.13`) kısıtı ve `uv.lock` bunu telafi eder.

`docs/team-contract.md:12` bunu "geçiş dönemi uyumluluk/dışa aktarım listesi" olarak
açıklamaktadır — yani bilinçlidir. Ancak jüri `pip install -r requirements.txt` derse farklı
sürümlerle farklı davranış alabilir. Freeze'den önce ya silinmeli ya sabitlenmelidir.

---

### D13 — `RawStorage._find_existing` her yazımda tüm kaynak ağacını tarıyor

**Sınıf:** Planlanmış eksik / ölçeklenme riski — `Koddan gözlemlendi`
**Alan:** Operasyonel dayanıklılık

`src/lakehouse/storage/raw.py:126-136`: her `store()` çağrısında kaynağın tüm RAW ağacında
`rglob(f"{digest}.*")` taraması yapılır ve eşleşme bulunursa dosyanın tamamı okunup baytları
karşılaştırılır. Birkaç yüz artifact'ta sorun değildir; on binlerce EVDS serisi çekildiğinde
ingestion süresi belirgin biçimde büyür.

**Bu bir ölçüm değil, kod okumasına dayalı bir çıkarımdır.** Gerçek etki ölçülmemiştir.

---

### D14 — `sql_guard` yaygın sütun adlarını yanlış pozitif olarak reddedebilir

**Sınıf:** Planlanmış eksik (bilinçli savunma derinliği tercihinin yan etkisi)
**Alan:** Bakım kolaylığı

`src/lakehouse/security/sql_guard.py:18-44` — reddedilen anahtar kelime listesi sorgudaki
**tüm sözcüklere** uygulanır. Yani `set`, `load`, `call`, `copy`, `use`, `merge` gibi
sözcükler sütun veya takma ad olarak kullanılırsa sorgu reddedilir. String literal'ler
doğru biçimde muaf tutulmuştur (`:105`, `:134`) — bu iyi.

Ayrıca reddedilen dış erişim fonksiyonları bir **denylist**'tir (`:45-68`); DuckDB'ye yeni
eklenen bir dosya okuma fonksiyonu listede olmayabilir.

**Bu neden P2:** Gerçek bariyer denylist değil, bağlantı sertleştirmesidir
(`read_only` + `enable_external_access=false` + `lock_configuration=true`) ve `QueryExecutor`
bunu ayrıca doğrulamaktadır (`src/lakehouse/query/executor.py:28-53`). Kod bunu docstring'de
açıkça "savunma derinliği" olarak konumlandırmıştır. Bkz. §12.

---

## 12. Yanlış alarm olabilecek noktalar

Aşağıdakiler ilk bakışta kusur gibi görünebilir ancak **bulgu sayılmamalıdır**. Bunları
"düzeltmeye" çalışmak zaman kaybı olur.

**Y1 — "357 test 1,65 saniyede geçiyor, demek ki yüzeysel."**
Hayır. Testler bilinçli olarak fixture-replay yöntemiyle yazılmıştır; hiçbiri socket açmaz
ve bu **her ilgili test dosyasının docstring'inde açıkça yazılıdır** (örn.
`tests/integration/test_evds_kfe_source_integration.py:1-16`: "This is an offline test of
real code, **not** a live call to EVDS"). Bu iyi mühendisliktir. Gerçek eksik "testlerin
hızlı olması" değil, **canlı doğrulamanın hiç olmamasıdır** (D3).

**Y2 — "Parser tarihi normalize etmiyor, eksik."**
Hayır — **Silver'a ait beklenen iştir**. `src/lakehouse/parsers/evds.py:16-27` bunu kaynak
davranışıyla gerekçelendirir: `Tarih` alanı frekansa göre biçim değiştirir, bu yüzden ham
bırakılır ve `UNIXTIME` bir sonraki katmana devredilir. Bu bilinçli bir katman ayrımıdır.

**Y3 — "`sql_guard` denylist yaklaşımı, atlatılabilir."**
Kısmen doğrudur ama abartılmamalıdır — bkz. D14. Gerçek bariyer bağlantı sertleştirmesidir.
Bu tasarım agent ekibinin kendi geçici çözümünden **daha iyidir** ve agent ekibi bunu
kendi belgesinde yazmıştır: "`_verify_untrusted_connection` yaklaşımı (SQL Guard'ı tek
bariyer bırakmamak) agent tarafındakinden ileri; onu bizim tarafa da alıyoruz."
(`LAKEHOUSE_BUILD_PLAN.md`, "Kurduğunuz şey sağlam" bölümü — dosyanın konumu için
§20.6'daki kaynak konumu notuna bakınız) `Dokümantasyon iddiası`

**Y4 — "`meta.series` içinde yalnızca 4 seri var, katalog çalışmıyor."**
Katalog **yükleyicisi** çalışmaktadır ve kalitelidir. Eksik olan **içeriktir**, kod değil.
Bu ayrım önemlidir çünkü çözümü de farklıdır (§13, Ö4).

**Y5 — "Boş `provenance/`, `quality/`, `semantics/`, `tools/` paketleri terk edilmiş kod."**
Hayır; bunlar bilinçli olarak ayrılmış sınırlardır ve docstring'lerinde "reserved for future"
yazmaktadır. Ancak jüri algısı açısından D10 ile birlikte değerlendirilmelidir.

**Y6 — "`ParquetStorage.register_local_parquet` hiç kullanılmıyor, ölü kod."**
Hayır — üç entegrasyon testinde kullanılmaktadır
(`tests/integration/test_infrastructure_vertical_slice.py:53`,
`test_bddk_weekly_source_integration.py:162`, `test_phase_1b_source_integration.py:112`).
Gerçek sorun kullanılmaması değil, **üretim kodunda bir üst seviye sarmalayıcısının
olmamasıdır** (D1).

---

## 13. Yeni ve özgün geliştirme fırsatları

> **Bu bölüm ÖNERİLERDİR. Hiçbiri uygulanmamıştır ve hiçbiri mevcut implementasyonu
> tarif etmez.** Mevcut durum §7 ve §8'dedir.

Aşağıdakiler mevcut ekip dokümanlarında (`progress.md`, `LAKEHOUSE_BUILD_PLAN.md`,
`docs/lakehouse-nihai-karar.md`) geçmeyen, koddan ve yarışma beklentilerinden türetilmiş
önerilerdir.

### Ö1 — Sorgu sonucuna yapışık provenance zarfı

**Değer.** Sunum s.7'nin alt bandı "Güven katmanı: Kaynak gösterimi – İzlenebilirlik –
Doğruluk Kontrolü" ayrı bir değerlendirme kalemidir. Provenance verisi **zaten mevcuttur**
(`meta.artifact`, `meta.artifact_request`, parser uyarıları) ancak sorgu sonucuna kadar
taşınmamaktadır: bugünkü `QueryResult` yalnızca `columns`, `rows`, `row_count`, `truncated`,
`executed_sql` içerir (`src/lakehouse/query/executor.py:57-64`). Sonuca kaynak adı, kaynak
URL'si, `artifact_sha256` listesi, `fetched_at` listesi ve uyarılar eklemek **yeni veri
toplamayı gerektirmez**, yalnızca mevcut olanı bağlamayı gerektirir.

**Jüriye gösterimi.** Agent bir grafik ürettiğinde altında: "Kaynak: TCMB EVDS `TP.KTF12`,
çekilme 2026-09-14 06:15 UTC, artifact `a3f9…`, uyarı: yok."

**Risk / yeni karmaşıklık.** Düşük. Mevcut sözleşmeler değişmez; `query/` içinde yeni bir
tip eklenir.
**Silver bağımsızlığı:** ✅ Tam · **Çakışma ihtimali:** Düşük ·
**3 güne uygunluk:** ✅ · **Ne zaman:** Şimdi (D1'in doğal parçası)
**Doğrulama testi:** Materyalize edilmiş bir tablo üzerinde çalıştırılan sorgunun sonucunda
en az bir `artifact_sha256` ve bir `fetched_at` değerinin döndüğünü gösteren test.

### Ö2 — "Kanıt paketi": tek komutla doğrulanabilirlik

**Değer.** Organizatör "demo ortamını kendimizin de kendi ortamında hazırlayıp ayağa
kaldırabilmemiz çok kritik" demiştir (Transkript `00:24:11`). Tek bir komutun RAW artifact
sayısını, SHA-256'ların yeniden hesaplanıp kayıtla eşleştiğini, Bronze satır sayılarını,
katalog seri sayısını, uyarı sayısını ve son çalıştırma zamanlarını raporlaması, "verinin
doğru olduğunu nasıl biliyorsunuz" sorusuna 5 saniyede cevap verir.

**Risk.** Yok. Salt okunur bir rapor üreticisidir.
**Silver bağımsızlığı:** Kısmi (Silver satırlarını da kapsaması gerekir) ·
**Çakışma ihtimali:** Düşük · **İş:** Küçük · **Ne zaman:** Silver sonrası
**Doğrulama testi:** Bilerek bozulmuş bir RAW dosyasında komutun hash uyuşmazlığını
raporladığını gösteren test.

### Ö3 — Agent sözleşmesine uyum testi (contract conformance test)

**Değer.** Agent ekibi `LAKEHOUSE_CONTRACT.md` içinde altı metotluk bir `LakehouseClient`
protokolü tanımlamıştır (`list_datasets`, `get_dataset`, `search_datasets`, `execute_sql`,
`preview`, `health`) ve şu anda **geçici bir stub** ile çalışmaktadır
(`agent-core/src/kkb_agent/adapters/duckdb_lakehouse.py`, `origin/feature/agent-engine`
dalında). Data tarafında bu protokolü uygulayan hiçbir şey yoktur. **İki ekip freeze'e 10 gün
kala birbirine hiç bağlanmamıştır.** Aynı uyum testinin hem stub'a hem gerçek uygulamaya
karşı geçmesi, "modüler yapı" iddiasının somut kanıtı olur.

**Risk.** Düşük; ancak sözleşmenin agent ekibiyle birlikte teyit edilmesi gerekir.
**Silver bağımsızlığı:** ✅ Tam · **Çakışma ihtimali:** Düşük (agent-core dalına
dokunulmaz) · **İş:** Küçük (protokol zaten yazılı) · **Ne zaman:** Şimdi
**Doğrulama testi:** Protokolün altı metodunun da uygulandığını ve beklenen tipleri
döndürdüğünü doğrulayan uyum testi.

### Ö4 — Katalog kapsamını üretici bir yaklaşımla genişletmek

**Değer.** 4 seriden anlamlı bir kapsama çıkmak. On binlerce seriyi elle yazmak imkânsızdır
ve `semantic_confidence` disiplini buna izin vermez. Öneri: kaynağın kendi seri listesinden
**taslak** kayıtlar üretmek (`status: draft`, `semantic_confidence: unknown`) ve yalnızca
demo senaryosunda geçen sınırlı sayıda seriyi elle `verified` seviyesine yükseltmek.
Şema buna zaten izin vermektedir: `sql/bootstrap/004_series_catalog.sql:50-52`'deki
`series_draft_requires_no_dataset` kısıtı tam bu senaryo için yazılmıştır.

**Jüriye gösterimi.** "Katalogda N seri var, M tanesi insan tarafından doğrulanmış, agent
yalnızca doğrulanmış serilerde otomatik frekans/kümülatif dönüşümü yapıyor" — dürüstlüğün
mimariye gömülmesi.

**Risk.** Taslak kayıtların yanlışlıkla `active` sayılması — şema bunu zaten engellemektedir.
**Silver bağımsızlığı:** ✅ Tam · **Çakışma ihtimali:** Düşük · **İş:** Orta ·
**Ne zaman:** Taslak üretimi şimdi başlayabilir, `verified` yükseltmeleri Silver sonrası
**Doğrulama testi:** `status='draft'` bir serinin agent yüzeyinde aktif seri olarak
listelenmediğini gösteren test.

### Ö5 — Demo günü için çevrimdışı yeniden üretim modu

**Değer.** Demo günü kaynak erişilemezse veya TLS/ağ sorunu çıkarsa sunum çöker. RAW deposu
**zaten içerik-adresli ve değişmezdir**; bir kez çekilen veri diskte durur. Bir ortam
bayrağıyla connector'ları devre dışı bırakıp doğrudan RAW'dan yeniden ayrıştırmak neredeyse
maliyetsizdir.

**Risk.** "Hile" algısı. Bu yüzden açıkça belgelenmeli ve `meta.artifact.fetched_at` ile
verinin ne zaman gerçekten çekildiği gösterilebilmelidir.
**Silver bağımsızlığı:** ✅ Tam · **Çakışma ihtimali:** Düşük · **İş:** Çok küçük ·
**Ne zaman:** Freeze'den hemen önce
**Doğrulama testi:** Ağ erişimi olmayan bir ortamda tüm Bronze'un RAW'dan yeniden
üretilebildiğini gösteren test.

### Ö6 — Şema değişimi (schema drift) tespiti

**Değer.** `schema_version_sha256` Bronze yoluna **zaten gömülüdür**
(`src/lakehouse/storage/parquet.py:80-89`), yani kaynak alan ekler/çıkarırsa yeni bir yola
yazılır ve eskisiyle karışmaz. Ancak kimse "şema değişti" diye haber vermemektedir. Aynı
`dataset_id` için ikinci bir `schema_version` görüldüğünde uyarı üretmek küçük bir eklemedir.

**Risk.** Yok. **Silver bağımsızlığı:** ✅ Tam · **Çakışma ihtimali:** Düşük ·
**İş:** Çok küçük · **Ne zaman:** D2 ile birlikte
**Doğrulama testi:** Aynı `dataset_id` için iki farklı `schema_version` yayınlandığında
uyarı kaydı oluştuğunu gösteren test.

### 13.1 Şu an ÖNERİLMEYENLER ve nedenleri

| Fikir | Neden şimdi değil |
|---|---|
| LanceDB / embedding tabanlı seri arama | Kloudeks bağımlılığı; 10 günde ölçülebilir fayda yok. `meta.series.aliases` + DuckDB FTS yeterli. |
| `dbt` | Sade SQL runner yeterli; ekibin P2 kararı (`progress.md` R bölümü, karar 3) doğru. |
| DuckLake / Iceberg / Delta | P1 kararı doğru; V1 için gereksiz karmaşıklık. |
| Genel OCR / PDF ingestion pipeline'ı | Agent ekibinin Web URL Tool kapsamında (Sunum s.10, s.13). |
| Data Passport, semantic firewall | Kavramsal olarak çekici; 10 günde ölçülebilir değer üretmez. |
| Gelişmiş dashboard | Agent/frontend kapsamı. |
| `sql_guard`'ı baştan yazmak | Gerçek bariyer bağlantı sertleştirmesidir; guard bilinçli savunma derinliğidir (§12, Y3). |

---

## 14. Elif için Silver'dan bağımsız aday işler

Puanlama 1–5 arasındadır; **"Çakışma riski" sütununda düşük puan iyidir.**

| # | Aday iş | İlgili bulgular | Yarışma değeri | Risk azaltma | Silver bağımsızlığı | Çakışma riski | Süre | Test edilebilirlik | Demo görünürlüğü | Toplam |
|---|---|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **A** | Yayın katmanı + agent SQL yüzeyi | D1, D5, D2, Ö1, Ö3 | 5 | 5 | 5 | 2 | 2–3 gün | 5 | 5 | **31** |
| **B** | Uyarı ve çalıştırma kaydı kalıcılaştırma | D2, Ö6 | 4 | 5 | 5 | 2 | 0,5 gün | 5 | 3 | **28** |
| **C** | EVDS pencereleme + gözlem sayısı doğrulaması | D4 | 4 | 5 | 5 | 1 | 0,5–1 gün | 5 | 2 | **28** |
| **D** | Registry + CLI + CI | D6, D9 | 4 | 4 | 4 | 2 | 1,5 gün | 4 | 4 | **26** |
| **E** | FinTürk connector/parser | D7 | 4 | 2 | 5 | 1 | 2 gün | 4 | 3 | **24** |

**Puanlama notu.** A'nın çakışma riski 1 değil 2'dir: `sql/bootstrap/` dosya numaralandırması
ve `meta.*` tablo isimleri Sena ile ortak alandır. Bunun nasıl yönetileceği §16'dadır.

---

## 15. Önerilen ana görev ve yan görev

> **Öneridir; uygulanmamıştır.**

### Ana görev: **A — Yayın katmanı ve agent SQL yüzeyi**

**Neden diğerlerinden önce gelmeli:**

1. **Tek gerçek yol tıkanıklığı budur.** B, C, D ve E'nin hepsi Bronze'u iyileştirir. A
   olmadan Bronze'daki hiçbir iyileştirme agent'a ulaşmaz — Silver bitse bile ulaşmaz.
2. **Sena'yı beklemez, ama Sena'yı bekletir.** Sena Silver'ı bitirdiğinde "çıktımı nereye
   yazayım" diye soracaktır. A o soruya hazır cevap üretir. Şimdi yapılmazsa Silver
   bittikten sonra yapılır ve o zaman **kritik yolda** olur.
3. **Ampirik olarak kanıtlanmış bir tuzağı kapatır.** `enable_external_access` geri
   açılamamakta ve kayıtlı ilişki üzerine kurulan view sessizce bozulmaktadır (D1,
   `Yerel deneyle doğrulandı`). Bunu bilmeden Silver yazan biri iki gün kaybeder.
4. **Agent ekibi hâlâ stub ile çalışmaktadır** ve 10 gün kalmıştır. İki katmanın hiç
   buluşmamış olması projenin en büyük entegrasyon riskidir (§19-A3).
5. **Jüri kriterine doğrudan denk düşer.** Provenance verisi zaten vardır; A onu görünür
   kılar (Sunum s.7 alt bant).

**Kapsam (öneri).** Ayrıntılı sınırlar §16, kabul kriterleri §17'dedir. Özet:

- Bronze/Silver çıktısını DuckDB'de kalıcı tabloya materyalize eden idempotent bir bileşen
  (tek çalışan yol: Python okuma → `register()` → `CREATE TABLE … AS SELECT`)
- `meta.dataset_version` ve `meta.run` tablolarının gerçekten yazılması (D5)
- Parser uyarılarının kalıcı bir tabloya yazılması (D2) ve şema drift uyarısı (Ö6)
- Agent sözleşmesindeki okuma arayüzünün uygulanması (Ö3), mevcut `QueryExecutor` ve
  `sql_guard` **değiştirilmeden** kullanılarak
- Sorgu sonucuna provenance zarfı eklenmesi (Ö1)
- Silver'ın çıktısını nasıl teslim edeceğini anlatan bir sözleşme belgesi — **Sena'nın
  koduna dokunmadan Sena'yı yönlendiren doküman**

**Neden B ayrı bir ana görev değil:** Çok değerli ve çok ucuzdur, ancak A'nın provenance
zarfı (Ö1) zaten uyarıları taşımayı gerektirir. B'yi A'nın kapsamına gömmek daha tutarlıdır.

### Yan görev: **C — EVDS pencereleme**

- Yarım gün, tek dosya (`src/lakehouse/connectors/evds.py` — Elif'in kendi dosyası),
  **sıfır çakışma**.
- Organizatörün açık bir gereksinimini (5 yıllık derinlik, Sunum s.9) sessiz bir hatadan
  kurtarır.
- A'nın uzun ve düşünce gerektiren bölümleri arasına "temiz kazanç" olarak sığar.

### Neden D ve E şimdi değil

**D (registry + CLI)** A'nın üstüne oturur; A olmadan CLI'nin gösterecek bir sonucu yoktur.
**E (FinTürk)** yeni kaynak ekleme işidir; Bronze bir kaynak eksiğiyle bile çalışır, ama son
metre olmadan hiçbiri çalışmaz. Ayrıca E canlı doğrulama gerektirir ve D3'teki erişim
belirsizliği çözülmeden risklidir.

---

## 16. Önerilen çalışma sınırları ve olası branch çakışmaları

> **Öneridir. Bu denetimde hiçbir branch açılmamış, değiştirilmemiş veya temizlenmemiştir.**

### 16.1 Ana görev A

**Önerilen branch adı:** `feature/lakehouse-publication-surface`
**Önerilen taban:** `feature/lakehouse-integration` @ `ae22de7`

**Dokunulabilecek dosya ve klasörler (öneri):**

```
src/lakehouse/publish/                    (YENİ — materyalizasyon)
src/lakehouse/tools/                      (bugün boş — okuma arayüzü buraya)
src/lakehouse/ingestion/pipeline.py       (yalnızca: uyarı + çalıştırma kaydı bağlama)
src/lakehouse/query/executor.py           (yalnızca: sonuca provenance zarfı ekleme)
sql/bootstrap/005_publication.sql         (YENİ — numarayı Sena ile teyit et)
tests/publish/, tests/tools/              (YENİ)
docs/publication-contract.md              (YENİ)
docs/branches/lakehouse-publication-surface.md (YENİ — repo geleneğine uygun)
```

**Kesinlikle dokunulmaması önerilen alanlar:**

```
src/lakehouse/connectors/*                (yan görev C hariç, o da AYRI branch'te)
src/lakehouse/parsers/*
src/lakehouse/contracts/models.py, identifiers.py, types.py   ← ORTAK SÖZLEŞME
src/lakehouse/catalog/series.py                               ← katalog yükleyici
models/silver/, models/gold/                                  ← Sena
catalog/series/*.yml                                          ← içerik işi, ayrı görev
src/connectors/, src/parsers/, src/storage/, src/contracts/   ← shim'ler (D10, ekip kararı)
sql/bootstrap/001–004                                         ← mevcut migration'lar değişmez
agent-core/  (origin/feature/agent-engine dalı)               ← agent ekibi
```

### 16.2 Sena'nın Silver çalışmasıyla olası çakışma noktaları

| Nokta | Risk | Önerilen yönetim |
|---|---|---|
| `sql/bootstrap/` dosya numarası | **Orta** — ikisi de `005_*.sql` yazabilir | Numara rezervasyonu üzerinde önceden anlaşılmalı (ör. Elif `005_`, Sena `006_`) |
| `meta.*` tablo isimleri | **Orta** | Yayın tabloları `meta.*` altında Elif'e ait; Silver kendi tablolarını `silver.*` şemasında tutmalı |
| `src/lakehouse/ingestion/pipeline.py` | Düşük — Bronze ingestion'a aittir, Silver'ın dosyası değildir | Değişiklik minimal ve yalnızca ekleme (additive) tutulmalı |
| `src/lakehouse/contracts/models.py` | **Yüksek olurdu — bu yüzden yasak listesinde** | `ParsedBatch` / `FetchSpec` **hiç değişmemeli**; provenance zarfı `query/` içinde yeni bir tip olarak yaşamalı |
| `docs/publication-contract.md` | Düşük — yeni dosya | Yazıldığı an Sena'ya iletilmeli |
| `src/` shim ağacı (D10) | **Orta–yüksek** | Sena'nın import'larını kırabileceği için bu görev kapsamında **kesinlikle silinmemeli** |

### 16.3 Yan görev C

**Önerilen branch adı:** `feature/source-access-evds-windowing` (A ile karışmaması için ayrı)
**Dokunulabilir:** `src/lakehouse/connectors/evds.py`,
`src/lakehouse/parsers/evds.py` (yalnızca gözlem sayısı doğrulaması),
`tests/connectors/test_evds_connector.py`, `docs/sources/evds.md`
**Dokunulmaz:** Diğer her şey
**Çakışma:** Yok — bu dosyalar Elif'in kendi çalışma alanıdır.

---

## 17. Kabul kriterleri ve gerekli testler

> **Öneridir.**

### 17.1 Ana görev A — bitmiş sayılma kriterleri

1. Bir Bronze Parquet dosyası yayın bileşeniyle DuckDB'ye materyalize edilir ve
   `connect_untrusted` + `QueryExecutor` üzerinden **doğru satırlarla okunabilir**.
2. Aynı yayın iki kez çalıştırıldığında sonuç aynıdır; `meta.dataset_version` içinde
   mükerrer satır oluşmaz (idempotentlik).
3. Kırpılmış veya tutarsız bir fixture ingest edildiğinde uyarı kaydı kalıcı bir tabloda
   görünür ve çalıştırma durumu `success` **değildir**.
4. Agent sözleşmesindeki altı metot uygulanmış ve `meta.series` içeriğini bulabiliyordur.
5. Sorgu sonucunda dönen provenance zarfı en az bir `artifact_sha256` ve bir `fetched_at`
   içerir.
6. **Mevcut 357 testin hiçbiri kırılmaz**; toplam test sayısı artar.
7. `make test`, `make build` ve `make demo-check` temiz bir makinede geçer.

### 17.2 Gerekli testler (öneri)

| Test dosyası (önerilen) | Kapsam |
|---|---|
| `tests/publish/test_materializer.py` | İdempotentlik, sürüm kaydı, trusted-bağlantı zorunluluğu |
| `tests/publish/test_run_and_warnings.py` | Uyarı kalıcılaşması (D2), şema drift uyarısı (Ö6) |
| `tests/tools/test_lakehouse_client.py` | Altı metot + provenance zarfı (Ö1, Ö3) |
| `tests/integration/test_bronze_to_agent_surface.py` | RAW → Bronze → yayın → `connect_untrusted` → `QueryExecutor` uçtan uca |
| **Regresyon (kritik)** | "Kayıtlı ilişki üzerine oluşturulan view sonraki bağlantıda okunamaz" — D1'deki tuzağın tekrarını engeller |

### 17.3 Integration dalına alınmadan önce kontrol listesi

- [ ] `git status` temiz; yalnızca izin verilen dosyalar değişmiş
- [ ] `src/lakehouse/contracts/models.py`, `src/lakehouse/catalog/series.py`,
      `src/lakehouse/connectors/*`, `src/lakehouse/parsers/*` diff'te **yok**
- [ ] Tüm testler geçiyor ve yeni sayı raporlanmış (357 → yeni değer)
- [ ] `sql/bootstrap` dosya numarası Sena ile teyit edilmiş
- [ ] `docs/publication-contract.md` yazılmış ve Sena'ya iletilmiş
- [ ] Agent ekibine "protokol uygulandı, stub değiştirilebilir" bildirimi yapılmış
- [ ] `docs/branches/…` belgesi eklenmiş (repo geleneği)
- [ ] Hiçbir sırrın veya API anahtarının diff'e girmediği doğrulanmış
- [ ] `git diff --check` temiz

### 17.4 Yan görev C — bitmiş sayılma kriterleri

1. Gözlem sınırını aşan bir aralık istendiğinde connector birden fazla pencere isteği yapar.
2. Her pencere RAW'a ayrı bir artifact olarak iner.
3. Birleşik gözlem sayısı beklenenle eşleşir; eşleşmezse `OBSERVATION_COUNT_MISMATCH`
   yükseltilir.
4. `docs/sources/evds.md` güncellenir ve gözlem sınırı iddiasının doğrulanma durumu
   açıkça yazılır.

---

## 18. Şimdi yap / Silver sonrası yap / ekip kararı bekle / yapma

> **Bu bir öneri listesidir; hiçbir madde uygulanmamıştır.**

### ✅ Şimdi yap

| İş | İlgili bulgu | Not |
|---|---|---|
| **A — Yayın katmanı + agent SQL yüzeyi** | D1, D5, D2, Ö1, Ö3 | Ana görev; §15–§17 |
| **C — EVDS pencereleme** | D4 | Yan görev; ayrı branch, yarım gün |
| **EVDS API anahtarı tedariki** | D3 | **Kod değil, tedarik işi.** Geciktikçe tüm EVDS hattı spekülatif kalır. §19-A2 |
| **CI workflow'u** | D9 | ≈40 satır; 10 gün, 3 kişi, paralel dallar. Getiri/maliyet oranı çok yüksek, kimseyle çakışmaz |
| **Kayıp worktree kaydının temizlenmesi** | S1 | `git worktree prune` — zararsız hijyen. Bu denetimde **yapılmamıştır** |

### ⏸️ Sena Silver'ı bitirince yap

| İş | İlgili bulgu | Neden şimdi değil |
|---|---|---|
| Registry + CLI | D6 | A'nın üstüne oturur; önce A bitmeli |
| Kanıt paketi (`make evidence`) | Ö2 | Silver satırlarını da kapsamalı |
| Katalog `verified` yükseltmeleri | D7, Ö4 | Demo senaryosu netleştikten sonra. **Taslak üretimi şimdi başlayabilir** |
| Çevrimdışı demo modu | Ö5 | Freeze'den hemen önce anlamlı |
| `RawStorage` tarama performansı | D13 | Önce gerçek hacim çekilip ölçülmeli; şimdi optimize etmek erken |

### 🤝 Mentor veya ekip kararı bekle

| Konu | İlgili bulgu | Karar verilmesi gereken soru |
|---|---|---|
| **`main` dalı ve freeze stratejisi** | S2, S3, §5 #19 | Freeze anında jüri hangi dalı görecek? `main` ne zaman, nasıl güncellenecek? **Geciktirilmemeli.** |
| **FinTürk kapsamı** | D7 | Organizatör açıkça saydı (Sunum s.8). Kapsama alınacak mı, alınacaksa kim yapacak? Şu an sahipsiz |
| **BDDK TLS çözümü** | D8 | CA bundle repoya mı konacak, kurulum adımı olarak mı belgelenecek? Güvenlik puanı açısından mentora sorulabilir |
| **`src/` shim ağacı** | D10 | Silinmesi Sena'nın import'larını kırabilir. Önce sorulmalı, sonra karar verilmeli — freeze'den önce |
| **`progress.md` güncelliği** | D11 | Kimin güncelleyeceği ekipçe kararlaştırılmalı; tek kişinin işi değil |
| **`requirements.txt`** | D12 | Silinsin mi, sabitlensin mi? (`uv.lock` zaten doğru yol) |
| **Agent ekibiyle sözleşme buluşması** | Ö3, §19-A3 | İki katman 10 gün kala hiç bağlanmamış. Toplantı ayarlanmalı |

### 🚫 Yapma (şu an)

- Silver koduna dokunmak, Silver Acceptance Pack hazırlamak, Silver'a bağlı entegrasyon
  testleri yazmak, Gold'a başlamak
- LanceDB / embedding tabanlı seri arama
- `dbt` entegrasyonu
- DuckLake / Iceberg / Delta geçişi
- Genel OCR / PDF ingestion pipeline'ı
- Data Passport, semantic firewall, gelişmiş dashboard
- Ortak sözleşmeleri (`src/lakehouse/contracts/models.py`, `src/lakehouse/catalog/series.py`) değiştirmek
- `sql_guard`'ı "denylist zayıf" gerekçesiyle baştan yazmak (§12, Y3)

---

## 19. Açık sorular ve dış bağımlılıklar

### A1 — Freeze anında hangi branch değerlendirilecek? `Teyit gerekli`

**Durum.** Transkript `00:22:54`–`00:23:04`: "Siz freeze ettiğiniz anı zaten klonlayacağız …
demolarınızı da GitHub'ta en son komitlediğiniz hali üzerinden yapacaksınız."
Sunum s.16'da 20 Eylül tarihi verilmiştir. Sunum s.22: teslimat GitHub üzerinden KKB'ye
erişim verilerek yapılacaktır.

**Belirsizlik.** "Klonlanacak an" ifadesi varsayılan dalı mı, tüm dalları mı kapsar
belirsizdir. `origin/main` şu anda `lakehouse-core/` dizinini **içermemektedir** (S2).
Ana çalışma `feature/lakehouse-integration` dalındadır.

**Aksiyon.** Slack üzerinden mentora sorulmalı; paralel olarak `main`'in güncellenmesi
planlanmalıdır. **Bu, kod kalitesinden bağımsız olarak projeyi görünmez kılabilecek bir
risktir.**

### A2 — EVDS API anahtarı ne zaman gelecek? `Teyit gerekli`

D3'ün tamamı buna bağlıdır. Anahtar olmadan resmî uç noktaya tek bir doğrulama çağrısı
yapılamaz ve mevcut tüm EVDS fixture'ları spekülatif kalır. Bu **kodla çözülemeyecek bir
dış bağımlılıktır** ve başvuru gecikirse etkisi büyür.

### A3 — Agent katmanı ile veri katmanı ne zaman buluşacak? `Teyit gerekli`

Agent ekibi geçici bir stub ile çalışmaktadır (S5). Sözleşme yazılıdır ancak uygulanmamıştır.
10 gün kalmıştır. Bir entegrasyon buluşması ve ortak bir uyum testi (Ö3) planlanmalıdır.

### A4 — Organizatörün "tüm seriler" ifadesinin kapsamı nedir? `Teyit gerekli`

Sunum s.9 "Seriler içerisindeki tüm veriler" demektedir. Bunun pratik anlamı (tüm EVDS
serileri mi, demo senaryosunu kapsayan alt küme mi) mentora sorulmalıdır. Cevap, D7 ve
Ö4'ün kapsamını doğrudan belirler.

### A5 — BDDK TLS iddiası hâlâ geçerli mi? `Teyit gerekli`

Docstring'lerdeki ara sertifika iddiası 2026-09-08/09 tarihli gözlemlere dayanmaktadır
(`Dokümantasyon iddiası`). Sunucu yapılandırması değişmiş olabilir. Demo öncesi bir kez
kontrol edilmelidir.

### A6 — EVDS gözlem sınırı gerçekten 1000 mü? `Teyit gerekli`

`src/lakehouse/connectors/evds.py:11-12, 38` bunu TCMB kılavuzuna dayandırmaktadır.
Bu denetimde resmî kılavuz indirilmemiş ve doğrulanmamıştır. D4'ün çözüm tasarımı bu değere
bağlıdır; A2 ile birlikte doğrulanmalıdır.

---

## 20. Yeniden üretilebilir doğrulama prosedürleri

Bu bölüm, rapordaki iddiaların bağımsız olarak yeniden üretilebilmesi içindir.
Aşağıdaki komutlar `AgentSmithler_WorkSpace/` kökünden veya belirtilen dizinden çalıştırılır.
**Hiçbiri proje dosyasını değiştirmez.**

### 20.1 Belge kimliğinin doğrulanması

```bash
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git rev-list --left-right --count origin/feature/lakehouse-integration...HEAD
git status --porcelain
```

Beklenen: `feature/lakehouse-integration`, `ae22de71dcdd29e8b83e00200be4f8e038759058`,
`0	0`, boş çıktı.

### 20.2 Test sayısının doğrulanması

```bash
cd lakehouse-core && uv run pytest -q --no-header -p no:cacheprovider
```

Beklenen: `357 passed`, exit code 0. `-p no:cacheprovider` bayrağı pytest cache'inin
değişmemesi içindir.

Testlerin proje dosyalarını değiştirmediğini doğrulamak için, çalıştırma öncesi ve sonrası:

```bash
git status --porcelain          # her ikisinde de boş olmalı
find lakehouse-core/data -type f # her ikisinde de boş olmalı
```

### 20.3 D1'in yerel deneyle doğrulanması (yerel deney — silindi)

> **Bu bir yerel deneydir.** Denetim sırasında oturuma özel scratchpad dizininde
> çalıştırılmış ve **sonrasında silinmiştir**. Repoda kalıcı bir kanıt dosyası **yoktur**;
> aşağıdaki prosedür deneyin yeniden üretilmesi içindir. Deney projeden bağımsız, geçici
> bir DuckDB dosyası ve geçici bir Parquet dosyası üzerinde yapılmıştır; `lakehouse-core`
> içindeki hiçbir dosyaya dokunulmamıştır.

Yaklaşım (proje dışında, geçici bir dizinde):

1. pandas ile küçük bir DataFrame oluşturup geçici bir Parquet dosyasına yaz.
2. Geçici bir DuckDB dosyası aç ve `SET enable_external_access = false` uygula
   (bu, `src/lakehouse/db/connection.py:38-55`'in yaptığı şeyin aynısıdır).
3. **Gözlem 1:** `CREATE VIEW … AS SELECT * FROM read_parquet('<geçici>.parquet')` çalıştır.
   Beklenen sonuç: `PermissionException: … file system operations are disabled by
   configuration`.
4. **Gözlem 2:** Aynı bağlantıda `SET enable_external_access = true` çalıştır.
   Beklenen sonuç: `InvalidInputException: Cannot enable external access while database
   is running` — yani ayar geri alınamaz.
5. **Gözlem 3:** Parquet'i Python tarafında oku, `connection.register("rel", df)` ile kaydet,
   ardından `CREATE TABLE t AS SELECT * FROM rel` çalıştır. Beklenen sonuç: **başarılı**.
6. **Gözlem 4:** Aynı kayıtlı ilişki üzerine `CREATE VIEW v AS SELECT * FROM rel` çalıştır.
   Beklenen sonuç: view **oluşur**. Bağlantıyı kapat, veritabanını salt-okunur ve
   sertleştirilmiş biçimde yeniden aç, `SELECT * FROM v` çalıştır.
   Beklenen sonuç: `CatalogException: Table with name rel does not exist` — yani view
   kalıcıdır ama kayıtlı ilişki oturum ömürlüdür.
7. Karşılaştırma için `SELECT * FROM t` çalıştır. Beklenen sonuç: **satırlar döner**.

Deney sırasında kullanılan DuckDB sürümü projenin `uv.lock` dosyasındaki sürümdür.

### 20.4 Bulguların koddan doğrulanması

```bash
cd lakehouse-core

# D2 — uyarıların üretim kodunda tüketicisi var mı?
grep -rn '\.warnings' src/ tests/          # src/ altında tüketici çıkmamalı

# D4 — pencereleme kodu var mı?
grep -rniE 'window|chunk|paginat|split_range' src/   # yalnızca yorum satırları çıkmalı

# D5 — ölü meta tabloları
grep -rnE 'meta\.run|dataset_version|meta\.source' src/ tests/
grep -rn 'run_id' src/                      # yalnızca identifiers.py çıkmalı

# D6 — çalıştırılabilir giriş noktası
grep -rnE 'if __name__|argparse|click|typer|def main' src/   # boş dönmeli

# D7 — katalog kapsamı ve FinTürk
for f in catalog/series/*.yml; do echo "$f: $(grep -c 'series_id:' "$f")"; done
grep -rni 'finturk\|fintürk' src/ tests/ catalog/ sql/ docs/

# D8 — TLS güvenliği ve CA bundle
grep -rn 'verify=False' src/                # boş dönmeli (TLS zayıflatılmıyor)
grep -rniE 'REQUESTS_CA_BUNDLE|certifi|ca_bundle' src/ docs/   # boş dönüyor (eksik)

# D12 — bağımlılık sabitlemesi
uv lock --check
cat requirements.txt
```

### 20.5 Git topolojisinin doğrulanması

```bash
git worktree list
git branch -a -vv
git ls-tree -r --name-only origin/main | head
git diff --stat origin/feature/lakehouse-main-ready origin/feature/lakehouse-integration
```

### 20.6 Agent sözleşmesinin okunması

Agent tarafı sözleşmeleri bu repoda **başka bir dalda** durmaktadır; `lakehouse-core`
içinden göreli bir bağlantıyla erişilemez:

```bash
git show origin/feature/agent-engine:docs/LAKEHOUSE_CONTRACT.md
git show origin/feature/agent-engine:docs/LAKEHOUSE_BUILD_PLAN.md
git show origin/feature/agent-engine:agent-core/src/kkb_agent/adapters/duckdb_lakehouse.py
```

> **Kaynak konumu notu.** Bu raporda adı geçen `LAKEHOUSE_BUILD_PLAN.md`, `progress.md`,
> `docs/lakehouse-nihai-karar.md` ve `references/` altındaki transkript/sunum dosyaları
> **git deposunun içinde değil**, deponun bir üst dizinindeki çalışma alanındadır
> (`kkb hackathon/`). `LAKEHOUSE_BUILD_PLAN.md`'nin bir kopyası ayrıca
> `origin/feature/agent-engine` dalında `docs/LAKEHOUSE_BUILD_PLAN.md` olarak durmaktadır.
> Bu yüzden rapordan bu dosyalara göreli bağlantı verilmemiştir.

---

## 21. Sonuç ve uygulama yapılmadığına dair not

### Sonuç

Data/Lakehouse temeli **kaynak erişimi ve ham veri saklama ekseninde güçlü, veri yayınlama
ekseninde boştur**. Mühendislik kalitesi, dokümantasyon dürüstlüğü ve güvenlik disiplini bu
yarışma için beklenenin üstündedir; bunlar jüri karşısında korunması gereken değerlerdir.

Buna karşılık üç şey demo gününü doğrudan tehdit etmektedir: **EVDS'in resmî uç noktasının
hiç doğrulanmamış olması**, **Bronze'dan agent'a giden yolun ürünleşmemiş olması** ve
**uyarıların kaybolmasıyla oluşan sessiz veri kaybı riski**. Bunların üçü de Silver'dan
bağımsızdır ve Sena'nın çalışmasıyla çakışmadan ele alınabilir.

Önerilen ana görev — **yayın katmanı ve agent SQL yüzeyi** — bu risklerden ikisini
kapatırken aynı zamanda projenin en büyük entegrasyon riskini (agent katmanının hâlâ bir
stub'a bağlı olması) da azaltmaktadır.

### Uygulama yapılmadığına dair not

> **Bu rapor herhangi bir uygulama yapıldığı anlamına gelmez.**
>
> Bu belge yalnızca bir denetim ve değerlendirme çıktısıdır. Raporun hazırlanması sırasında:
>
> - Hiçbir kaynak kodu dosyası oluşturulmamış, değiştirilmemiş veya silinmemiştir.
> - Hiçbir test, SQL dosyası, katalog dosyası veya şema dosyası değiştirilmemiştir.
> - Hiçbir doküman (bu rapor dışında) değiştirilmemiştir.
> - Branch açılmamış, değiştirilmemiş; commit, push, merge, rebase, stash veya worktree
>   temizliği yapılmamıştır.
> - Hiçbir gerçek veri kaynağına canlı istek gönderilmemiş, API anahtarı kullanılmamış ve
>   hiçbir dış sistemin durumu değiştirilmemiştir.
> - Testler yalnızca **çalıştırılmış**, sonuçları raporlanmıştır; çalıştırma sonrası
>   çalışma ağacının temiz kaldığı doğrulanmıştır.
> - D1'i doğrulamak için kullanılan yerel deney, projeden bağımsız geçici bir dizinde
>   yapılmış ve **silinmiştir**; prosedürü §20.3'tedir.
>
> Rapordaki §13, §14, §15, §16, §17 ve §18 bölümleri **önerilerdir**. Hiçbiri uygulanmamıştır
> ve hiçbiri mevcut mimariyi tarif etmez. Mevcut durum §7 ve §8'de, bulgular §9–§11'dedir.
>
> Bir sonraki adımın hangi iş olacağı **ekibin kararına bırakılmıştır**.

---

*Rapor sonu. Branch `feature/lakehouse-integration`, commit `ae22de7`, 357 test geçti.*
