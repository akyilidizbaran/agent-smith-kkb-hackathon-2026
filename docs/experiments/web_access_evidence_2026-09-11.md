# Web erişim engelleri — somut kanıt (11 Eylül 2026)

Amaç: V3 §3.8'deki "üyelik / CAPTCHA / bot engeli" iddiasını mentöre götürmeden önce gerçek sitelerde doğrulamak.
Yöntem: `curl -sL` ile ham HTML, tarayıcı User-Agent'ı ve `python-requests` User-Agent'ı ile; HTML'de `recaptcha|paywall|login|register` sayımı ve yönlendirme zinciri. LLM yok, JS çalıştırılmadı.
Etiket: tüm satırlar `[EMP]` (bu oturumda ölçüldü), aksi belirtilmedikçe.

| # | Site / URL | Ne oldu | Engel türü | Ajan için anlamı |
|---|---|---|---|---|
| 1 | Moody's — Türkiye devlet notu özeti `https://www.moodys.com/credit-ratings/Turkiye-Government-of-credit-rating-768337/summary` | `HTTP 302 → /account/sign-in?ReturnUrl=…` (tarayıcı UA ve python UA'da aynı). Gelen sayfa JS kabuğu, metin yok. | **Giriş zorunlu** | Rapor URL'si verilse bile ajan login sayfasına düşer → `AUTH_REQUIRED` |
| 2 | S&P Global Ratings — araştırma listesi `https://www.spglobal.com/ratings/en/research/articles` | `HTTP 403`, gövde: "Error — Security Controls Triggered" (her iki UA'da) | **Bot / WAF engeli** | İnsan tarayıcı görür, otomatik istemci hiç göremez; hesap açmak bile çözmez |
| 3 | Statista — Türkiye konut fiyat endeksi `https://www.statista.com/statistics/1114425/…` | 200; HTML'de `paywall` ×98, `Premium` ×166, `RECAPTCHA` ×1; metin: "Register for free… Access limited to Free Statistics. Premium Statistics are not included." | **Üyelik + ücretli katman + reCAPTCHA** | Ücretsiz kayıt bile premium veriyi açmaz; kayıt formu reCAPTCHA'lı |
| 4 | REIDIN — Türkiye gayrimenkul verisi `https://reidin.com/tr/` | 200; HTML'de `recaptcha` ×9; tek erişim yolu "Ücretsiz Demo Talep Edin" formu (reCAPTCHA'lı) | **Abonelik / demo talebi + reCAPTCHA** | Herkese açık indirme yok; ajan talep formunu dolduramaz (dolduramamalı) |
| 5 | Borsa İstanbul DataStore `https://datastore.borsaistanbul.com/` | 200 ama gövde 1.8 KB JS kabuğu (Ember SPA); `/login`, `/register` rotaları var. Veri dosyaları 2015'ten beri yalnızca burada, üyelikle `[SRC]` (arama sonucu) | **Üyelik + JS-only sayfa** | Düz fetch ile içerik yok; tarayıcı otomasyonu + hesap gerekir |
| 6 | TCMB EVDS `https://evds2.tcmb.gov.tr` → `evds3` | API anahtarı ücretsiz kayıtla veriliyor `[SRC]` (resmî yönerge; GitHub istemci README'leri) | **Anahtar = platform hesabı** | Bugün `.env`'de tuttuğumuz model; "ekip servis hesabı" yaklaşımının çalışan örneği |

Kontrol edilip **engel bulunmayan** (karşılaştırma için): GYODER yayınlar sayfası (200, 145 KB, işaretleyici yok). Fitch raporu: sayfa 2 MB, login/register işaretleri var ama rapor metni kısmen açık; sonuç belirsiz, tabloya alınmadı.

## Çıkarımlar

1. Üç farklı engel sınıfı var ve hepsi ayrı davranış ister: (a) giriş yönlendirmesi (Moody's), (b) WAF 403 (S&P), (c) JS kabuğu (DataStore, Moody's). §3.8'deki `AUTH_REQUIRED` yalnızca (a)'yı kapsıyor; (b) için `BLOCKED_BY_SITE`, (c) için `JS_RENDER_REQUIRED` (veya headless tarayıcı) kodları gerekir.
2. "Ücretsiz kayıt" çoğu zaman yeterli değil (Statista premium, REIDIN demo talebi). Ekip hesabı yaklaşımı yalnızca gerçekten üye olunmuş kaynaklarda işe yarar.
3. CAPTCHA kayıt formlarında (Statista, REIDIN); kayıt sonrası oturumda görülmedi. Bu, "hesabı insan açar, ajan oturumu kullanır" modelini destekler.

## Tekrar üretme

```bash
curl -sL -A "Mozilla/5.0" -o /dev/null -w "%{http_code} %{url_effective}\n" \
  "https://www.moodys.com/credit-ratings/Turkiye-Government-of-credit-rating-768337/summary"
curl -s  -A "Mozilla/5.0" -o /dev/null -w "%{http_code}\n" \
  "https://www.spglobal.com/ratings/en/research/articles"
curl -sL -A "Mozilla/5.0" "https://www.statista.com/statistics/1114425/turkey-house-price-index/" \
  | grep -oiE "recaptcha|paywall|premium" | sort | uniq -c
curl -sL -A "Mozilla/5.0" "https://reidin.com/tr/" | grep -oic recaptcha
curl -sL -A "Mozilla/5.0" -w "size=%{size_download}\n" -o /dev/null "https://datastore.borsaistanbul.com/"
```
