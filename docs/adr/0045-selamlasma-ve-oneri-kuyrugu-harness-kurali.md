# ADR-0045: Yalnız sorulana cevap — selamlaşma LLM'e gitmez, öneri kuyruğu kırpılır

**Durum:** Kabul edildi · **Tarih:** 2026-09-13 · **Sıradaki:** E kapanış

## Bağlam
Arayüzde düz "selam" yazıldığında model emoji, madde madde öneriler ("taşıt, ihtiyaç kredisi…
makro karşılaştırma… ne yapmak istersin?") ve önceki analizin özetini döktü; arayüz de altına
eski tabloyu yeniden çizdi. Kullanıcı: yalnız sorulana cevap. Sebep iki yerde ölçüldü:
1. Sistem promptunda "istenmemişi yazma" kuralı yoktu; her turda aktif tablo, son 8 tur ve
   katalog kartları modele gidiyor, cevaplanacak veri sorusu olmayınca model bu bağlamı "devam
   menüsü" olarak sunuyor (sohbet modellerinin varsayılan asistan refleksi).
2. Arayüz her cevaptan sonra workspace'in aktif tablosunu gösteriyordu; cevap tabloya
   dokunmasa da.

## Karar
1. **Selamlaşma harness'te biter** (`core/small_talk.py`): mesajın tüm sözcükleri dar bir
   selam/teşekkür/onay sözlüğünden ve rakam/veri sözcüğü yoksa LLM çağrılmaz; tek cümle
   ("Selam. Sorunu yazabilirsin." + varsa "Aktif tablo duruyor…"), tablo ve kanıt paneli yok,
   iz "selamlaşma — LLM çağrılmadı". Yanlış sınıflama riski dar sözlükle sıfıra yakın:
   "selam, 2025 konut…" selam değildir.
2. **Prompt kuralı:** "YALNIZ sorulana cevap ver. İstenmemiş öneri, seçenek listesi, 'başka ne
   yapabilirim' kapanışı ve emoji yazma. Cevap bitince dur."
3. **Deterministik kuyruk kırpma:** cevabın sonunda "Başka bir soru istersen / İstersen /
   Örneğin: / Ne yapmak istersin" ile açılan paragraf ve sonrası düşer; öncesinde anlamlı içerik
   yoksa dokunulmaz (cevap boş kalmaz). Emoji kaldırılır. Tarihçe kırpılmış metinle güncellenir;
   iz "öneri kuyruğu kırpıldı" notu taşır.
4. **Arayüz:** tablo yalnız bu cevap ürettiyse ya da ele aldıysa gösterilir (tablo nesnesi
   değişti ya da veri üreten/işleyen bir araç başarıyla çalıştı).

## Sonuçlar
- Selam sıfır token; demo izinde görünür ("harness güçlü, LLM'e en az iş").
- Kırpma yalnız kuyruk için; ortadaki "Örneğin Haziran'da…" cümleleri kalır (test).
- Reddedilen: selamı LLM'e kısa promptla göndermek (token ve gecikme; kazanç yok);
  öneri kuyruğunu yeniden ürettirmek (bir tur daha, kırpma yetiyor).
