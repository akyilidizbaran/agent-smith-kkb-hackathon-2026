# Sıfırdan kurulum (SETUP)

Bu belge projeyi hiç görmemiş biri içindir. Adımlar sırayla yapılır; her adımın sonunda neyi görmeniz gerektiği yazılıdır.
Süre: bağımlılık kurulumu birkaç dakika; veri havuzu seçtiğiniz kapsama ve bağlantınıza göre (adım 5) — küçük set tam
havuzdan çok daha kısa sürer, tam havuz birkaç saat olabilir.

---

## 0. Gerekenler

| Ne | Neden | Nasıl |
|---|---|---|
| **Git** | Repoyu indirmek | macOS: `xcode-select --install` · Windows: [git-scm.com](https://git-scm.com) |
| **uv** | Python sürümü ve bağımlılıklar (Python'u ayrıca kurmanız gerekmez) | macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh \| sh`<br>Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| **make** | Kısa komutlar (isteğe bağlı) | macOS/Linux'ta var. Windows'ta yoksa aşağıdaki "make olmadan" komutlarını kullanın. |
| **Kloudeks (MIA) API anahtarı** | Metin, embedding ve OCR modelleri | Hackathon ekibinden alınır |
| **TCMB EVDS API anahtarı** | EVDS serilerini çekmek | [evds3.tcmb.gov.tr](https://evds3.tcmb.gov.tr) → üye ol → profil → API anahtarı |
| Tavily API anahtarı (isteğe bağlı) | Ajanın web araması | [tavily.com](https://tavily.com); yoksa web araması kapalı kalır, gerisi çalışır |
| Google Chrome (isteğe bağlı) | Yalnız JavaScript ile yüklenen web sayfalarını okumak | Kurulu Chrome kullanılır; ek tarayıcı indirilmez |
| ~2 GB boş disk | Ham dosyalar, Parquet, veritabanı | — |

Kurulumdan sonra terminali kapatıp açın ve `uv --version` ile uv'nin geldiğini kontrol edin.

---

## 1. Repoyu indirin

```bash
git clone https://github.com/bushushow/AgentSmithler_WorkSpace.git
cd AgentSmithler_WorkSpace
git checkout main
```

**Görmeniz gereken:** kök dizinde `README.md`, `SETUP.md`, `agent-core/`, `lakehouse-core/`, `Makefile`.

---

## 2. Bağımlılıkları kurun

```bash
make setup
```

<details><summary>make olmadan</summary>

```bash
cd agent-core && uv sync --frozen --extra dev && cd ..
cd lakehouse-core && uv sync --frozen && cd ..
```
</details>

İki ayrı sanal ortam kurulur: `agent-core/.venv` (Python ≥ 3.11) ve `lakehouse-core/.venv` (Python 3.12). uv gereken
Python sürümünü kendisi indirir.

**Görmeniz gereken:** iki komut da hatasız biter (`Installed … packages`).

---

## 3. Ortam dosyasını hazırlayın

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

`.env` dosyasını bir metin düzenleyiciyle açın ve **yalnız şu satırları** doldurun:

```dotenv
MIA_API_KEY=<Kloudeks anahtarınız>
EVDS_API_KEY=<EVDS anahtarınız>
TAVILY_API_KEY=<isteğe bağlı>
```

Geri kalan her şeyin varsayılanı çalışır. Birkaç önemli ayar:

| Ayar | Varsayılan | Ne zaman değiştirilir |
|---|---|---|
| `LAKEHOUSE_PATH` | `data/lakehouse.duckdb` (repo köküne göre) | Veritabanını başka yerde tutacaksanız mutlak yol verin |
| `AGENT_PROFILE` | `analyst` | Sunucu Architect (dosyayı havuza kaydetme) açık başlasın isterseniz `architect` |
| `PROFILE_SWITCH` | `token` | Arayüzdeki Analyst/Architect düğmesi. `token`: Architect'e geçiş `ARCHITECT_TOKEN` ister. `open`: anahtarsız tek tık (yalnız güvenilen, kapalı ortamda) |
| `ARCHITECT_TOKEN` | boş | `token` kipinde Architect'e geçmek için belirleyeceğiniz parola |

> `.env` git'e girmez; anahtarlarınızı kimseyle paylaşmayın ve repoya yazmayın.

---

## 4. Ön kontrol

```bash
make preflight
```

<details><summary>make olmadan</summary>

```bash
cd agent-core && uv run python -m kkb_agent.cli --preflight && cd ..
```
</details>

**Bu aşamada beklenen** (veri henüz kurulmadı):

```text
  ✓ model              https://mia.csp.kloudeks.com/v1 · deepseek-ai/DeepSeek-V4.1-Flash · anahtar var
  ✓ anahtarlar         MIA var · EVDS var · Tavily var (yalnız var/yok)
  ✗ veri kökü          …/data
  ✗ veritabanı         …/data/lakehouse.duckdb yok · veri kurmak için: make demo-data
  ✗ izinli dosya kökü  …/data/incoming yok → … make demo-data oluşturur
SONUÇ: HAZIR DEĞİL — veri kökü, veritabanı, izinli dosya kökü
```

Bu üç ✗ normaldir; bir sonraki adım (veri kurulumu) üçünü de oluşturur. **Model ya da anahtar satırında ✗ varsa**
`.env`'e dönün.

Canlı model bağlantısını da denemek için: `cd agent-core && uv run python -m kkb_agent.cli --preflight --live`
(son satır `MIA canlı … cevap: 'hazır'` olmalı).

---

## 5. Veri havuzunu kurun

Havuz, kaynaklardan (BDDK, TCMB EVDS) **canlı** çekilerek kurulur: bootstrap → çekim (RAW → Bronze) → Silver → Gold.
İnternet bağlantısı ve EVDS anahtarı gerekir. İki seçenek var:

**a) Hızlı deneme — küçük set (önerilen ilk kurulum, tam havuzdan çok daha kısa):**

```bash
cd agent-core && uv run python scripts/build_demo_data.py --set demo && cd ..
```

~127 seri: seçilmiş BDDK aylık kalemleri, haftalık konut kredisi ve temel EVDS serileri (kur, faiz, TÜFE…).

**b) Tam havuz — katalogdaki tüm seriler (uzun sürer, birkaç saat olabilir):**

```bash
make demo-data
```

BDDK aylık ve haftalık bülten, FinTürk'ün 81 ili ve birimi tanımlı EVDS serileri, 2016'dan bugüne.

Kurulum sırasında adımların ilerlemesi ekrana yazılır. Komut mevcut veritabanını silmez; yarıda kalırsa aynı komutu
yeniden çalıştırabilirsiniz. Baştan kurmak için `--fresh --yes` ekleyin (mevcut veritabanını ve ham dosyaları siler).

**Görmeniz gereken:** `data/` klasöründe `lakehouse.duckdb`, `raw/`, `bronze/` oluşur. Ardından:

```bash
make preflight
```

Artık bütün satırlar ✓ ve son satır **`SONUÇ: hazır`** olmalı. Veri satırı yüklü seri ve gözlem sayısını gösterir.

---

## 6. Arayüzü başlatın

```bash
make serve
```

<details><summary>make olmadan</summary>

```bash
cd agent-core && uv run python -m kkb_agent.serve
```
</details>

Tarayıcıda **http://127.0.0.1:8765** adresini açın.

**Görmeniz gereken:** sol panelde katalog/yüklü seri/gözlem sayıları, üstte "Veri havuzu bağlı · deepseek-ai/…" ve
**Analyst | Architect** düğmesi, sağda "Kanıt zinciri" paneli.

İlk deneme soruları:

- `Elimizde hangi veriler var?`
- `2025 yılında aylık TÜFE genel endeksini getir.`
- `BDDK aylık bültenden 2024-2025 konut kredisi bakiyesini aylık getir ve grafiğini çiz.`

Her cevapta sağdaki panel sayıları tabloya, SQL'e ve kaynak dosyaya bağlar. Tablolar CSV/XLSX, cevap HTML rapor olarak
indirilebilir.

**Dosya ile deneme:** mesaj kutusunun yanındaki 📎 ile bir CSV/XLSX/PDF yükleyip "Bu dosyayı analiz et" deyin. Dosyayı
havuza kaydetmek için Architect profiline geçip "Bu dosyayı havuza taslak seri olarak ekle" deyin; kataloğa alma sizin
açık onayınızla olur.

Sunucuyu durdurmak için terminalde `Ctrl+C`.

---

## 7. Testler (isteğe bağlı)

```bash
make test        # agent-core: ~1170 test, saniyeler; ağ ve anahtar gerekmez
make test-data   # lakehouse-core: uzun sürer
```

<details><summary>make olmadan</summary>

```bash
cd agent-core && uv run --frozen --extra dev pytest -q && cd ..
cd lakehouse-core && uv run --frozen pytest -q && cd ..
```
</details>

---

## 8. Sık karşılaşılan sorunlar

| Belirti | Neden | Çözüm |
|---|---|---|
| `ModuleNotFoundError: No module named 'kkb_agent'` | Başka bir sanal ortam etkin (`VIRTUAL_ENV`) | `deactivate` ya da `unset VIRTUAL_ENV` (Windows: `Remove-Item Env:VIRTUAL_ENV`), sonra komutu `agent-core` içinden tekrar çalıştırın |
| Ön kontrol: "veritabanı … yok" | Havuz kurulmadı ya da `LAKEHOUSE_PATH` başka yeri gösteriyor | Adım 5; repo dışında çalıştırıyorsanız `LAKEHOUSE_PATH` ve `DATA_ROOT` için mutlak yol verin |
| Ön kontrol: anahtar ✗ | `.env` doldurulmadı ya da yanlış klasörde | `.env` repo kökünde olmalı (`README.md` ile aynı yerde) |
| EVDS çekiminde hata | EVDS anahtarı yok ya da geçersiz | `.env` → `EVDS_API_KEY`; anahtarı EVDS profilinizden yenileyin |
| `Address already in use` (8765) | Port dolu | Eski sunucuyu kapatın ya da `.env`'de `WEB_PORT=8766` |
| Architect düğmesi gri | Profil geçişi kapalı | `.env`: `ARCHITECT_TOKEN=<parola>` (düğmeye basınca sorulur) ya da güvenilen ortamda `PROFILE_SWITCH=open`; sunucuyu yeniden başlatın |
| Web araması yok | Tavily anahtarı yok | İsteğe bağlı; `.env` → `TAVILY_API_KEY` |
| Bir sitede "otomatik erişimi engelliyor" | Sitenin bot koruması | Tasarım gereği aşılmaz; cevaptaki talimatla dosyayı indirip yükleyin |

---

## Sonra ne okumalı

| Belge | İçerik |
|---|---|
| [README.md](README.md) | Proje özeti ve belgelerin haritası |
| [01-GENEL-MIMARI.md](01-GENEL-MIMARI.md) | Katmanlar ve bir sorunun yolculuğu |
| [05-KURULUM-VE-CALISTIRMA.md](05-KURULUM-VE-CALISTIRMA.md) | Tüm ortam değişkenleri, komut satırı, başka alanla çalıştırma |
| [06-VERI-VE-KATALOG.md](06-VERI-VE-KATALOG.md) | Kaynaklar, katalog, Gold, taslak → onay akışı |
