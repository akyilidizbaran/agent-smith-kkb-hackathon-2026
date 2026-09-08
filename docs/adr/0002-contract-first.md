# ADR-0002: Veri katmanıyla sözleşme üzerinden paralel çalışma

**Durum:** Kabul edildi · **Tarih:** 2026-09-08

## Bağlam
Data Lakehouse'u üç kişilik ayrı bir ekip kuruyor. Agent katmanı ona bağımlı.
Teslime 12 gün kalmışken veri katmanının bitmesini beklemek, takvimin yarısını
harcamak demekti.

## Karar
İki katman arasına yazılı bir sözleşme kondu: `LakehouseClient` protokolü +
`DatasetSpec` semantic catalog şeması. Agent yalnızca bu sözleşmeye karşı yazılır.
Geliştirme süresince sözleşmenin DuckDB üzerinde çalışan bir referans
uygulaması (`DuckDBLakehouse`) kullanılır.

## Gerekçe
- İki ekip birbirini beklemeden ilerler.
- Agent hiçbir yerde tablo/kolon adı bilmez; şemayı çalışma anında katalogdan
  okur. Bu sayede veri ekibinin şeması bizim varsayımımızdan farklı çıksa bile
  agent kırılmaz.
- Şartnamenin *"platform jenerik olmalı, içi boşaltılıp bambaşka bir sağlık
  verisiyle çalışabilmeli"* maddesi mimari düzeyde karşılanır: yeni alan için
  yeni bir `LakehouseClient` uygulaması ve yeni katalog yeterlidir.

## Sonuçlar
Gerçek kırılma noktası tek: **katalog eksik doldurulursa.** Sözleşme dokümanında
veri ekibinden istenen asıl şey bu yüzden "veri" değil, doldurulmuş katalogdur.
Veri ekibi sözleşmeyi kendi P0 kararlarıyla doldurup geri verdi
(`docs/LAKEHOUSE_CONTRACT_FILLED.md`); arayüz farkları oradaki eşleme tablosuyla
yönetilecek.
