# ADR-0046: Araç turları 0, nihai anlatı 0,5 — cümleler değişir, sayılar değişmez

**Durum:** Kabul edildi · **Tarih:** 2026-09-13 · **Sıradaki:** E kapanış

## Bağlam
Her LLM çağrısı `temperature=0.0` ile gidiyordu (araç seçimi ve SQL kararlı, golden ve demo
tekrarlanabilir). Yan etki: aynı soruya kelimesi kelimesine aynı anlatı; kullanıcı bunu
robotik buldu. Çeşitlilik istenen yer yalnız anlatı; araç turlarında çeşitlilik "aynı soruya
farklı sayı" demektir.

## Karar
1. **İki sıcaklık.** Araç turları (arama, tanım, kırılım değerleri, cevaplayan SQL) 0,0.
   Cevaplayan veri geldikten sonraki turlar (`produced_data`: anlatı, hesap kolonu, gösterim)
   `narrate_temperature`; araçsız son tur ve adım limiti turu da aynı sıcaklıkla.
2. **Ayar:** `LLM_NARRATE_TEMPERATURE` (varsayılan 0,5; `Settings.narrate_temperature`,
   `AnalyticsAgent(narrate_temperature=)`; kod varsayılanı 0 → birim testler deterministik).
   Golden koşucusu ve kabul betiği ortam değişkenini 0'a zorlar: ölçüm deterministik kalır.
3. **Güvenlik ağı değişmedi:** grounding denetimi anlatıdaki her sayıyı araç çıktısıyla
   doğrular, uyuşmazsa geri gönderir; veri geldikten sonra çağrılan hesap kolonu SQL
   guard'ından geçer. Sıcaklık anlatımı değiştirir, sayı üretmez.

4. **Tekrar sorularda kopyalama yasağı.** Ölçüldü: aynı oturumda aynı soru, T=0,5'te bile
   birebir aynı cevap (benzerlik 1,00) — model tarihçedeki kendi cevabını kopyalıyor; sıcaklık
   buna çare değil. Harness, soru (noktalama/büyük-küçük farkı silinerek) daha önce sorulmuşsa
   modele giden soruya not ekler: "önceki cevabını kopyalama; aynı verilerle farklı kurgu ve
   cümleler; sayıları ve kaynağı değiştirme". Tarihçeye ham soru yazılır.

## Ölçüm (demo DB, "2025 konut kredisi aylık, en yüksek/en düşük artış")
| Deney | Değerler | Anlatı |
|---|---|---|
| Temiz ajan ×3, T=0,5 | tablo değer parmak izi 3/3 aynı; anlatıdaki 20–25 sayının tümü tabloda; grounding OK | 3/3 farklı |
| Temiz ajan ×3, T=0 (karşılaştırma) | 3/3 aynı | 3/3 farklı (uç noktada T=0 de birebir deterministik değil; kolon adı bakiye/value bile değişiyor) |
| Aynı oturumda tekrar, T=0,5, not yok | aynı | birebir aynı (1,00) |
| Aynı oturumda tekrar, T=0,5, kopyalama yasağı | aynı | farklı (benzerlik 0,49) |

Ders: "aynı cevap" şikâyetinin kaynağı sıcaklık değil tarihçeden kopyalamaydı; ikisi birlikte
çözüldü. Değer sabitliği sıcaklıktan bağımsız, guard'lardan geliyor.

## Sonuçlar
- Demo ve arayüz 0,5 ile; jüri anlatısı: "cümleler değişir, sayılar değişmez".
- Reddedilen: tüm turlarda 0,5 (SQL/kalem seçimi değişebilir); yalnız tekrar sorularda yeniden
  anlatım (ilk cevap her açılışta aynı kalırdı); ikinci bir anlatı çağrısı (ek maliyet).
