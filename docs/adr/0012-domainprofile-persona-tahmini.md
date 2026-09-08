# ADR-0012: Domain profilinin modelle tahmin edilmesi

**Durum:** REDDEDİLDİ (mekanizma kabul, tahmin reddedildi) · **Tarih:** 2026-09-09

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

## Sonuçlar
- Placeholder mekanizması yapılacak — **jeneriklik şartı için**, performans için değil.
- Runtime'da sınıflandırma yok: lakehouse'a ne yüklüyse domain odur, deploy
  anında bellidir. Her soruda yeniden karar vermek, cevabı zaten bilinen bir
  soruyu tekrar sormak olurdu; üstelik yanlış sınıflandırma riski eklerdi.
- Yan fayda: "sağlık verisi yüklendi, profil kendiliğinden türedi, aynı testler
  geçti" demek jenerikliğin kanıtı olur.
