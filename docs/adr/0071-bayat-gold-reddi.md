# ADR-0071 — Bayat Gold tablosundan sayı verilmez

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** düzeltme planı K02-T09 (A24) · **Değiştirdiği:** ADR-0031/0039'da
bayat Gold'un yalnız etiketlenmesi

## Bağlam

Silver yeniden kurulunca eski `gold.*` tablosu `meta.gold_build` parmak iziyle "⚠ BAYAT" diye işaretleniyordu; ama
`lakehouse_query` bu tablodan sorguyu çalıştırıyor, uyarı provenance'a düşse de eski değer cevaba girebiliyordu.

## Karar

- Adaptör `stale_gold_tables()` ile parmak izi canlı Silver'dan farklı tabloları listeler.
- `lakehouse_query` politikası SQL'de bayat bir `gold.*` kimliği görürse sorguyu çalıştırmadan `GOLD_STALE` ile reddeder
  (tekrar denemeyle çözülmez). Tablo kurulmaz, eski değer modele dönmez.
- İpucu: Gold araçları kayıtlıysa aynı hesap `gold_align` / `gold_join` ile canlı Silver'dan yeniden yapılır; değilse
  kullanıcıya tablonun bayat olduğu ve operatörün `python -m lakehouse gold` ile yeniden kurması gerektiği söylenir.
- Güncel Gold tabloları eskisi gibi sorgulanır.

## Sonuç

`tests/test_k02_bayat_gold.py`: bayat tabloda ret (kod, tekrar denenemez, tablo yok, eski 121 değeri içerikte yok) ve güncel
tabloda sorgu. Hata zarfının sabit kümesine `GOLD_STALE` eklendi.
