# İl sınırları (harita için)

`chart` aracı `chart_type=map` için bu dizinde `tr_provinces.geojson` arar (ADR-0032):

- Biçim: GeoJSON `FeatureCollection`; her feature bir il, `properties` içinde il adı taşıyan
  bir alan (`name`, `NAME_1`, `il`, `ad`, `province` … ilk bulunan kullanılır).
- Ad eşlemesi normalize edilir (`İstanbul` / `ISTANBUL` / `izmir` aynı anahtar); tabloda olup
  sınırı bulunmayan il denetçiyi durdurur, sessizce düşmez.
- Dosya repoda yok: dış bir veri dosyasıdır. Eklenirken bu dosyaya **kaynak URL, lisans ve
  indirme tarihi** yazılır. Dosya yokken araç politika katmanında durur ve çubuk grafik önerir.

Kaynak / lisans: (henüz eklenmedi)
