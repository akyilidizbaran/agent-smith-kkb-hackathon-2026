# ADR-0007: Golden set metni değil tabloyu denetler

**Durum:** Kabul edildi · **Tarih:** 2026-09-08

## Bağlam
"İyileştirdim" iddiasının objektif bir kanıtı olmadan ilerlemek, 12 günlük bir
takvimde körlemesine çalışmak demek. Bir regresyon testi gerekiyordu.

## Karar
Golden vakaları, LLM'in ürettiği serbest metni değil, **agent'ın ürettiği analiz
tablosunu** denetler: satır sayısı, sütunlar, kaynaktan doğrulanmış gerçek
değerler. Ek olarak `must_use_tools` ile doğru aracın seçilip seçilmediğine
bakılır.

## Gerekçe
- Serbest metni "doğru mu?" diye denetlemek güvenilmez; aynı doğru cevap yüzlerce
  farklı cümleyle ifade edilebilir.
- Tablo denetimi deterministiktir: 12 ay soruldu, 12 satır dönmeli.
- Beklenen değerler kaynağın kendisinden doğrulandı (2025/12 konut kredisi
  678.970 milyon TL = TP 678.912 + YP 58).
- Sonuç doğru olsa bile yanlış yoldan gelinmiş olabilir; nitekim G7'de model
  `compute_column` yerine `add_column` kullandı ve bunu yalnızca araç listesine
  bakınca gördük.

## Sonuçlar
Vakaların bir kısmı doğrudan yarışmanın örnek senaryosundan (G6, G7, G4), bir
kısmı ilk ölçümde **fiilen gözlemlenen** hatalardan türedi (G2 mükerrer sayım,
G3 modelin kendi aritmetiği).

## Düzeltme (2026-09-09): yanlışlıkla geçen kontroller

İki vakanın kontrolü, ölçülen davranış gerçekleşmese bile sağlanıyordu:

- **G5** `len(df.columns) >= 3` — uzun formatta TEK kalem gelse de sağlanıyordu.
  Yerine: iki ölçüm sütunu **veya** iki katı satır aranıyor.
- **G6** `len(df.columns) >= 3` — analiz tablosu zaten 4 sütunlu
  (`donem, tp, yp, toplam`) olduğundan sütun **hiç eklenmese bile** geçiyordu.
  Nitekim bir koşuda sütun eklenmediği halde vaka geçmiş görünmüştü. Yerine:
  `must_use_tools=["workspace_add_column"]` — davranışın kendisi kanıt.

Ders: bir kontrolün "geçmesi" yetmez; **geçmediği bir durum var mı** diye
sorulmalı. Her zaman geçen bir kontrol, kontrol değildir.

**Bilinen zayıflıklar:** G1'deki metin kontrolü (`answer_must_not_contain`)
kırılgan. Golden set'in kapsamı dar: hepsi tek veri kaynağı ve kredi kalemleri
üzerinden.
