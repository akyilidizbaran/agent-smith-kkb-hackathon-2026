# ADR-0055: Dışa aktarım — tam tablo CSV/XLSX, grafik PNG, HTML rapor; cevap sürümüne bağlı

**Durum:** Kabul edildi · **Tarih:** 2026-09-14 · **Milestone:** M14 · **Karar (K05):** CSV+XLSX, PNG, HTML

## Bağlam
Sohbette ilk 200 satır gösteriliyordu; tam tablo, grafik dosyası ve rapor indirilemiyordu. Kullanıcı
kararı: dosya giriş-çıkışı zorunlu; formatlar CSV+XLSX, PNG, HTML (PDF yok).

## Karar
1. **Tam tablo sunucuda, cevap sürümüne bağlı.** Her cevabın aktif tablosu kopyalanıp `tables[index]`'te
   tutulur; dışa aktarım önizlemeden değil bu kopyadan. Eski cevabın düğmesi eski tabloyu indirir.
2. **CSV:** UTF-8 BOM, `;` ayraç, `,` ondalık (Türkçe Excel doğrudan açar), tarih ISO. **XLSX:** gerçek
   sayı/tarih hücreleri, `notlar` sayfasında başlık + uyarılar + dışa aktarım zamanı; ±sonsuz boş.
3. **PNG:** grafik dosyası olduğu gibi (`/api/answers/{i}/chart/{k}.png`); yoksa 404, sahte başarı yok.
4. **HTML rapor:** tek dosya; soru (dosya yolu gizlenir), cevap, uyarılar/varsayımlar (kanıt boşlukları,
   kolon uyarıları, işaret uyarısı, sorudan gelen doğrulanmamış sayı), tam tablo, gömülü grafik, kanıt
   durumu (üç rozet), kaynaklar (SQL kaynakları, web sha256+zaman, artifact), model ve commit.
5. **Oturum verisi / ortak havuz** rozeti (M14-T02): kolon kaynağı web/dosya ise "oturum verisi
   (ortak havuza yazılmadı)", aksi hâlde "ortak veri havuzu".

## Sonuçlar
- Testler 353 → 356: 300 satırlık tablo CSV/XLSX'te tam gelir (A25), rapor eski cevabın sürümünü taşır
  ve uyarıları içerir (A26), sıfırlama sonrası 404.
- Sınır: tablolar süreç belleğinde (oturum ömrü); sunucu yeniden başlayınca gider (K07: tek bilgisayar demo).
