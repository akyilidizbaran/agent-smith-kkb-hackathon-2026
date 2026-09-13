# ADR-0028: Erişim politikası ve geri çekilme sözleşmesi

**Durum:** Kabul edildi · **Tarih:** 2026-09-12 · **Kaynak:** Mentör yanıtı, 12 Eylül (Büşra'nın dört sorusu)

## Bağlam
Web ve ingest araçları henüz yazılmadı; yazıldıklarında ilk karşılaşacakları şey
erişilemeyen kaynaklar olacak. Ekip bunu tahmin etmek yerine gerçek sitelerde denedi:
Moody's giriş sayfasına yönlendiriyor, S&P otomatik istemciye `403 "Security Controls
Triggered"` dönüyor (hesap olsa bile), Statista ve REIDIN reCAPTCHA'lı üyelik arkasında,
Borsa İstanbul DataStore JavaScript'siz açılmıyor.

Mentörün kuralı açık:
- Ajan hesap açmaz, CAPTCHA aşmaz, güvenlik mekanizmasını dolanmaz.
- Önceden açılmış ekip hesabı/anahtarı kabul; ama **config'e gömülmez**, env/secret katmanında durur.
- Erişilemeyen kaynakta ajan **açıkça söyler ve seçenek sunar**: yetkili credential →
  dosya yükleme → alternatif kaynak. Alternatif bulmak artı; **gizlice değil.**
- Kullanıcı "bu URL'den / bu kurumdan" dediyse **kaynak sadakati bir kısıttır**; başka
  kaynağın verisi ilk kaynaktan gelmiş gibi sunulmaz.
- Mimari "biz önceden hesap açarız" varsayımına bağlanmaz; hiç erişilemeyen URL'de bile
  kontrollü geriler.

Bunun ön koşulu, "erişemedim"in bir istisna değil bir **değer** olması. İstisna yalnız
"olmadı" der; karar için *neden*, *ne yapılabilir* ve *kaynak sabit mi* gerekir.

## Karar
Üç parça, hepsi deterministik, hiçbiri LLM'e sormaz.

**Sözleşme** — `contracts/access.py`:
- `AccessOutcome{status ∈ ok | needs_credential | blocked | not_found, reason, message, options, evidence}`
- `SourceConstraint{pinned, source_ref, phrase}` — kullanıcı kaynağı sabitledi mi
- `FallbackDecision{action ∈ proceed | ask_user | try_alternative, must_disclose, disclosure, options}`

**Politika** — `core/access_policy.py`:
- `classify_access(...)`: HTTP durumu, son URL, gövde işaretleri ve robots'tan sonuç
  üretir. Sıra en kesin işaretten başlar: robots → ulaşılamadı → 404/410 → 429 → 401 →
  giriş yönlendirmesi → 403 (bot işareti varsa `blocked`, yoksa `needs_credential`) →
  2xx içinde CAPTCHA/bot/paywall → `ok`.
- `credential_available(host)`: env'de anahtar **var mı** — değeri asla okumaz, mesaja
  koymaz. Bilinen eşleme (`evds*.tcmb.gov.tr → EVDS_API_KEY`), diğerleri
  `KKB_CREDENTIAL_<HOST>`.
- `detect_source_constraint(question)`: URL geçiyorsa, "bu siteden / şu linkten" varsa,
  ya da kurum adı "-den getir" hâlindeyse sabit. Tutucu: emin değilse serbest.
- `decide(outcome, constraint)`: erişildi → devam; erişilemedi + sabit → **sor**;
  erişilemedi + serbest → alternatif denenebilir, **açıkça söylenerek**.

**Hata zarfı** (ADR-0025) genişledi: `access` katmanı, üç kod — `NEEDS_CREDENTIAL`,
`ACCESS_BLOCKED`, `SOURCE_NOT_FOUND`. Üçü de tekrar denenemez: aynı kaynağı aynı
biçimde tekrar istemek sonucu değiştirmez; alternatif ayrı bir çağrıdır ve kararı
harness verir, model değil.

## Bot engeli ile üyelik ayrı sınıflar
Bir 403'ün iki anlamı var. Gövdede bot işareti varsa (`Security Controls Triggered`,
Cloudflare challenge, reCAPTCHA) bu `blocked`'tır ve **credential bir seçenek değildir** —
S&P örneğinde hesap olsa bile içeri almıyor, ve zaten aşılmaya çalışılmaz. İşaret yoksa
`needs_credential`'dır ve ekip anahtarı varsa seçenek olarak sunulur. Bu ayrım testte
sabitlendi: bot engelinde `use_credential` seçeneği hiç üretilmez.

## Modele ne gidiyor
```
ERİŞİM[blocked]: Sayfa CAPTCHA istiyor; otomatik olarak geçilmez.
SEBEP: captcha
SEÇENEKLER: upload_file: Dosyayı siz yükleyin | alternative_source: Başka bir kaynak arayayım
KURAL: KAYNAK SABİT. Kaynak değiştirme, alternatif verisi kullanma; kullanıcıya seçenekleri sun ve sor.
KULLANICIYA: Belirttiğiniz kaynağa (https://…) erişemedim: … Kaynağı siz belirttiğiniz için değiştirmeden önce soruyorum.
```
Sessiz geçiş yok: sebep, seçenekler ve kural her zaman yazılır. "Taranan ama
kullanılmayan sayfalar" cevaba değil kanıt paneline gider (mentör); `evidence` alanı
bunun için.

## Kim kullanacak
Architect rolü (`ingest_from_url`) ve `web_url` aracı bu tipi üretir; harness kararı
`decide` ile verir; Analist yalnız `render_for_model` çıktısını okur. Sözleşme araçlardan
önce yazıldı ki araçlar ona karşı kodlansın, tersi değil.

## Ölçüm
19 test: sınıflandırma tablosu (15 gözlem), Büşra'nın dört gerçek sitesi, credential
değerinin hiçbir çıktıda görünmemesi, bot engelinde credential seçeneğinin olmaması,
kaynak sabitleme (8 soru, 3'ü kasıtlı olarak serbest), karar matrisi, hata zarfı
dönüşümü ve tekrar denenemezlik.

## İlgili
ADR-0020 (adaptör sertleştirme), ADR-0021 (search katmanı), ADR-0023 (Tavily),
ADR-0025 (hata zarfı). Mentör kararları: bellek `kkb-mentor-kararlari`.
