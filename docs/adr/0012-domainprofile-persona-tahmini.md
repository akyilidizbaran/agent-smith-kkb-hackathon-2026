# ADR-0012: Domain profilinin modelle tahmin edilmesi

**Durum:** Mekanizma UYGULANDI, tahmin katmanı REDDEDİLDİ · **Tarih:** 2026-09-09

## Bağlam
System prompt'ta alan bilgisi koda gömülüydü: *"Sen Türkiye ekonomisi ve
bankacılık verileri üzerinde çalışan bir veri analisti ajansın."* Bu, şartnamenin
jeneriklik maddesine aykırı. Önerilen çözüm: rolü placeholder yapıp bir modelle
tahmin ettirmek.

## Karar
- **Kabul:** Alan bilgisi koddan çıkarılıp `DomainProfile` ile yapılandırmaya
  taşınacak (rol, hedef kitle, örnek varlık).
- **Reddedildi:** Bu alanların çalışma anında bir modelle **tahmin edilmesi**.
  Profil katalogdan deterministik türetilir; istenirse bootstrap anında bir kez
  LLM ile özetlenip dosyaya sabitlenir ve insan onayından geçer.

## Gerekçe (literatür)
[EMNLP 2024 Findings](https://aclanthology.org/2024.findings-emnlp.888/) — 4 model
ailesi, 2.410 soru, 162 rol: system prompt'a persona eklemek performansı
**iyileştirmiyor**. Kritik ayrıntı: *en iyi rolü seçmeye çalışan stratejiler,
rastgele rol seçmekten daha iyi sonuç vermiyor.* Yani tam olarak önerilen
"rol tahmin katmanı", ölçüldüğünde karşılığı çıkmayan bir yatırım.

Buna karşılık ölçülebilir kazanç **veri bağlamında**: ADR-0003'teki semantic
layer sayıları (%8,3 → %78,3).

## Uygulama (2026-09-09)
`src/kkb_agent/domain.py` içinde `DomainProfile`. Modele giden bütün metinler —
system prompt ve araç şemalarının `description` alanları — `{domain}`,
`{audience}`, `{example_table}`, `{example_measure}`, `{example_entity}` gibi yer
tutucularla yazıldı. `ToolRegistry` şema üretirken bu yer tutucuları profille
dolduruyor.

Profil `DomainProfile.from_catalog()` ile katalogdan **deterministik** türüyor:
kaynak adları alanı, en zengin tablonun kolon rolleri örnekleri veriyor. Üslup
tercihleri (`DOMAIN_DESCRIPTION`, `DOMAIN_AUDIENCE`) .env'den geçilebiliyor.

Türetmenin BDDK kataloğundaki çıktısı:

```
domain                  = 'BDDK kaynaklı veriler'
example_table           = 'bddk_aylik_krediler'
example_time_column     = 'donem'
example_category_column = 'kalem'
example_measure         = 'toplam'
example_entity          = 'Tüketici Kredileri - Konut'
```

**Kanıt olarak test:** `tests/test_domain_profile.py` aynı motoru bir sağlık
kataloğuyla kurup araç şemalarının o alana uyduğunu doğruluyor
(`hastane_basvurulari`, `basvuru_sayisi`, `Kardiyoloji`). Ayrı bir test, nötr
profille kurulan motorun metinlerinde hiçbir finans terimi geçmediğini kontrol
ediyor — kod tabanına yeniden alan örneği sızarsa yakalanır.

## Sonuçlar
- Placeholder mekanizması yapıldı — **jeneriklik şartı için**, performans için değil.
- Runtime'da sınıflandırma yok: lakehouse'a ne yüklüyse domain odur, deploy
  anında bellidir. Her soruda yeniden karar vermek, cevabı zaten bilinen bir
  soruyu tekrar sormak olurdu; üstelik yanlış sınıflandırma riski eklerdi.
- Yan fayda: "sağlık verisi yüklendi, profil kendiliğinden türedi, aynı testler
  geçti" demek jenerikliğin kanıtı olur.
