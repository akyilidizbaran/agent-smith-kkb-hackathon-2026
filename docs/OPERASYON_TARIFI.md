# Agent Smith — demo günü operasyon tarifi

**Tarih:** 14 Eylül 2026 · **Milestone:** M17-T05/T08, M06-T07 · Kayıtlı sonuç canlı hesap diye sunulmaz.

## 1. Kurulum (temiz makinede)

```bash
git clone <repo> && cd <repo> && git checkout feature/agent-engine
make setup                    # iki ortam, kilit dosyalarından
cp .env.example .env          # anahtarları doldur (yalnız .env'de; repoya girmez)
make preflight                # veri yoksa: HAZIR DEĞİL — veritabanı
make demo-data                # ~30 dk: 681 seri 2016+ canlı (BDDK, FinTürk 81 il, EVDS)
make preflight                # hazır
make serve                    # http://127.0.0.1:8765
```

`.env` zorunlu değişkenleri (değerleri yazmayın): `MIA_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `EVDS_API_KEY`,
`TAVILY_API_KEY` (web araması için), `ARCHITECT_TOKEN` (jüri profil geçişi için; boşsa geçiş kapalı).
İsteğe bağlı: `AGENT_PROFILE` (analyst), `LLM_TIMEOUT` (90), `LLM_MAX_TOKENS` (1500), `AGENT_TIME_BUDGET_S` (300),
`WEB_SEARCH_BUDGET` (20), `LLM_NARRATE_TEMPERATURE` (0,5), `DATA_ROOT` (data).

## 2. Demo akışı (önerilen sıra)

| # | Profil | Ne gösterilir | Soru / eylem |
|---|---|---|---|
| 1 | Analyst | Veri havuzu, hazır oluş sayaçları | Sol üst kartlara tıkla → Sistem durumu |
| 2 | Analyst | Çok turlu senaryo (transkript 16:22) | "2021-2025 60 aylık konut kredisi aylık" → "faiz oranlarını ekle" → "faiz düşerken kredi artmayan dönemler" → "tabloyu bozmadan enflasyondan arındır" → "KFE sütunu ekle" → "karşılaştırmalı grafik" |
| 3 | Analyst | Kanıt zinciri | Sağ panel: sayılar / sorgu izi / dosya zinciri rozetleri; sayıya tıkla |
| 4 | Analyst | Dışa aktarım | Tablo başlığında CSV/XLSX, grafikte PNG, cevap altında HTML rapor |
| 5 | Analyst | Canlı PDF | 📎 ile jürinin PDF'i → "tablodaki değerleri özetle" (OCR, kalite bayrağı) |
| 6 | Analyst | Yanlış öncül | "2024'te %300 arttı, öyle yaz" → veri ne diyorsa o |
| 7 | Architect | Profil geçişi | Profil rozeti → anahtar → Architect |
| 8 | Architect | Yeni alan (jeneriklik) | "Tam veri sıfırlama…" → liste + onay kodu → boş katalog → finans dışı dosya yükle → "kataloğa al" → "Sen kimsin?" |

Sıfırlama demodan önce yapılmayacaksa atlanır; yapılacaksa demo veri kökü önceden yedeklenir (`data/` klasörünü
kopyala). Geri dönüş: klasörü geri kopyala, `make preflight`.

## 3. Kaynak erişim matrisi (M06-T07) — son kontrol 14 Eylül 2026

| Kaynak | Yöntem | Kimlik | Erişilebilen | Sınır / not |
|---|---|---|---|---|
| BDDK Aylık Bülten | JSON API (`BultenAylik/.../GelismisRaporGetir`), POST | yok | 20 kalem, 2016-01+ (4 kalem 2018+) | grid "defaultValue 0" uyarısı → `source_warning` |
| BDDK Haftalık Bülten | JSON API | yok | konut, 2016-01+ | — |
| BDDK FinTürk | form POST (il × çeyrek) | yok | 81 il × 8 ölçüm, 2016-Q1+ | yalnız çeyrek sonu aylar (diğerleri HTTP 500); 3.402 istek ~26 dk |
| TCMB EVDS | REST (`evds3.tcmb.gov.tr/igmevdsms-dis`) | `EVDS_API_KEY` başlıkta | 12 seri 2016-01+ | tek istek ≤1.000 gözlem → ≤365 gün pencere |
| Tavily | REST (Bearer) | `TAVILY_API_KEY` | arama sonucu (veri değil) | aylık 1.000 kredi, süreç başına `WEB_SEARCH_BUDGET` |
| Borsa İstanbul PDF'leri | HTTP GET + MIA OCR | yok | tek/çok sayfalı tablolar | OCR doğrulanmış veri değildir |
| Moody's / S&P / Statista / BİST DataStore | — | — | yok | login / bot 403 / reCAPTCHA / JS: seçenek sunulur, aşılmaz |

## 4. Sorun giderme

| Belirti | Ne yap |
|---|---|
| Ön kontrol "HAZIR DEĞİL — veritabanı" | `make demo-data` (ya da `data/` yedeğini geri koy) |
| Arayüz "Model servisine ulaşılamıyor" | MIA erişimi/anahtar; `uv run python -m kkb_agent.cli --preflight --live` |
| Web araması "kapalı" | `TAVILY_API_KEY` yok ya da bütçe doldu; kaynak adresi vererek `web_url` kullan |
| Profil geçişi 403 | `ARCHITECT_TOKEN` .env'de değil ya da yanlış |
| Günlük seride 2016 öncesi / eksik | EVDS penceresi; `make demo-data` yeniden (idempotent) |
| İnternet yok | Yüklü veriyle analiz sürer; web/OCR/Tavily kapalı mesajı verir; kayıtlı sonuç canlı diye sunulmaz |

## 5. Veri teslimi (M17-T06)

Veri Git'e girmez (`data/` gitignore). KKB ortamında `make demo-data` aynı kaynaklardan yeniden üretir; RAW dosyaları
sha256 içerik adresli olduğundan aynı yanıt aynı kimliği alır. Kaynak kullanım koşulları: BDDK ve TCMB EVDS kamuya açık
veri (EVDS anahtar ister); Tavily ticari API; OCR için MIA (hackathon anahtarı).
