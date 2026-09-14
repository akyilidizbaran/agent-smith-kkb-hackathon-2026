# ADR-0066 — Yanlış sayıyı yayımlamayan deterministik son çıkış

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** bağımsız kontrol R02 → düzeltme D02 (M13, M16) ·
**Değiştirdiği:** ADR-0063'teki "geri göndermeden sonra not ekle" davranışı

## Bağlam

Araç Ocak=100, Aralık=110 döndürürken model her yeniden yazımda "Aralık bakiyesi 999 milyon TL" dediğinde harness iki geri
göndermeden sonra cevabı "(Not: … doğrulanamadı: 999)" uyarısıyla yayımlıyordu. Beşinci canlı koşudaki yanlış bakiye
(1.048.900 ↔ 678.970) bu yoldan geçmişti. Uyarı yanlış anlatıyı korur; "eksik kanıt uyarıyla gösterilebilir" tercihi
bilinen yanlış sayıyı cevapta tutmayı kapsamaz.

## Karar

- **Ayrım:** araç çıktısında karşılığı olmayan sayı (grounding MISS) desteklenmeyen iddiadır ve cevapta kalmaz. Kaynak
  zinciri eksik ama sayısı tabloda olan cevap ise kanıt rozetleriyle uyarılı gösterilir (değişmedi).
- **Son çıkış (`_final_exit`):** yeniden yazma hakları bitince doğrulanamayan sayıyı taşıyan birim — cümle, madde, markdown
  tablo satırı — çıkarılır; satırı kalmayan tablonun başlığı da düşer. Geriye anlamlı metin kalırsa "doğrulanamayan N ifade
  cevaptan çıkarıldı" notu eklenir (sayıyı tekrarlamaz). Kalmazsa model çağrılmadan deterministik cevap kurulur:
  "güvenilir bir açıklama üretemedim" + aktif tablonun hücrelerinden markdown özet. Tablo yoksa dürüst sınır cümlesi.
- **Her çıkış yolunda:** normal döngü, döngü kilidi sonrası araçsız son tur, adım sınırı ve süre bütçesi. Araçsız turda
  (önceki sohbetin tablosuyla) cevap aktif tablo, önceki tablolar ve bakış sorgularıyla denetlenir; tek doğrulanamayan
  sayı yeter (önce ≥2 idi).
- **Tutarlılık:** kanıt paneli, kaydedilen sohbet, arayüz yükü ve HTML rapor aynı son metinden kurulur. Çıkarılan ifadeler
  yalnız `AgentAnswer.rejected_claims`'te; izde sayı yalnız "grounding: MISS" etiketli ret kaydında kalır, rapora girmez.
- **Sınır:** son çıkış yeni model çağrısı yapmaz; sonsuz yeniden yazma döngüsü yoktur.

## Reddedilenler

- **Üçüncü, dördüncü geri gönderme:** olasılığı artırır, doğruluğu garanti etmez ve süre bütçesini yer.
- **Cevabı tümden bastırmak:** doğru cümleler ve tablo kullanıcıya ulaşmalı; yalnız desteklenmeyen birimler çıkar.

## Sonuç

`tests/test_agent_loop.py` D02 vakaları: her tur 999 diyen model (nihai metin, anlatı adımı ve sohbet 999 taşımaz, 110
tablodan gelir, model çağrısı sayısı sınırlı), doğru cümle korunup yanlış birim çıkar, doğru ve yuvarlanmış cevap değişmez,
adım sınırı yolu, araçsız turda tek yanlış sayı. Eski "uyarı eklendi" testi yeni kabule göre güncellendi.
