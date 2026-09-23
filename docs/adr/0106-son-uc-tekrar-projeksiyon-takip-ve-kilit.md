# ADR-0106: Son üç tekrar bulguları: kullanıcı tablosu, takip turu yönlendirmesi ve tablo kuşağı

**Durum:** Kabul edildi · **Tarih:** 2026-09-23 · **İlgili:** ADR-0104, ADR-0105

## Bağlam
ADR-0105'in bütün düzeltmeleriyle 71 vaka 3 tekrar koşuldu (`v2_deepseek_final_r3_20260923*`). Puanlayıcılar önceki
koşularla aynı: 27 sayısal vaka `score_v2.py`, 44 davranış vakası aynı rubrik talimatıyla çalışan üç incelemeci.

Genel ortalama 65,9'dan 67,4'e çıktı (ham çalışma tablosuyla puanlanınca). İlk kez kullanıcı tablosu da ayrıca puanlandı
(`run_v2.py` artık arayüz/CSV/XLSX'in gösterdiği projeksiyonu `table`, ham tabloyu `workspace_table` olarak yazıyor). Sayısal
vakalarda iki tablo arasında 8,6 puan fark çıktı: 72,2 ham, 63,6 kullanıcı. Yani ajan doğru tabloyu kuruyor ama kullanıcıya
eksik gösteriyordu.

Kök nedenler:
1. **Çıplak "kolon/oran" dönüşüm sayıldı.** F08.2 yalnız dışa aktarma istiyor ("kolonlar ve değerler aynı olsun"); tur niyeti
   dönüşüm dedi, dönüşüm geri göndermesi modeli istenmemiş aylık değişim hesaplamaya itti. Aynı yanlış pozitif P05.1 ("oran
   serisini ara"), A06.1 (kolon adı enjeksiyonu) ve S06.1'de de vardı.
2. **Projeksiyon türetilmiş kolona indirgedi.** Hesaplanan kolon varsa kullanıcı tablosu yalnız onu ve kimlik kolonlarını
   gösteriyordu; kaynak kolon yalnız belirli kelimelerle geri geliyordu:
   - F07 "Aylık farkı hesapla": stok düştü.
   - T05 "nominal ve reel aynı tabloda": CPI düştü.
   - F08 (hiç değişim istenmedi): üç bakiye düştü.
   - Q05 ve I08: ham değer düştü.
3. **Takip turu doğrudan sabit metinle kapandı.** Yeni seri/kaynak isteyen takipte (F03 "EVDS TÜFE'yi ekle", F01 dönem
   kırpması) model veri çekmeden cevap yazınca bayat tablo kapısı cevabı "mevcut analiz tablosuyla uyumlu değil" metniyle
   değiştiriyordu; modele hiç yol gösterilmiyordu.
4. **Döngü kilidi tablo değişimini görmedi.** T06'da model üç türetilmiş kolonu doğru hesapladı, dönemi daraltmak için
   `gold_join`'i yeniden çalıştırdı (tablo baştan kuruldu), aynı LAG çağrılarını yeni tabloda tekrarlamak istedi. Kilit
   imzası yalnız araç adı + argüman olduğu için bunlar DUPLICATE_CALL oldu ve tur türetilmiş kolonsuz kapandı.

## Karar
1. `_TRANSFORMATION_ASK` çıplak `oran|sütun|kolon` taşımaz. Bunlar ancak eylemle birlikte dönüşümdür: "kolon ekle/hesapla/
   oluştur/türet", "oranı hesapla/türet". `fark` çekimleri genişletildi ("farklara", "farkına"); "farklı" yine eşleşmez.
   Beş benchmark turunun niyet kaydı (P05.1, F08.2, A06.1, S06.1; D08.1 başka yoldan korunuyor) incelenip güncellendi.
2. Kullanıcı projeksiyonu (`web_app._compute_result_projection`):
   - Soru bu turda türetme (değişim/fark/yüzde) istemiyorsa hesaplanan kolonlar görünümü daraltmaz; tablo olduğu gibi
     (kanıt kolonları hariç) gösterilir.
   - "hesapla/compute/calculate" kaynak veri isteği sayılır: hesap tabloya kolon ekler, tabloyu değişime indirmez.
   - "göster" ile yalnız değişim isteği ve "yalnız/sadece değişim" eskisi gibi yalnız türetilmiş kolonları gösterir.
     "Yalnız" değişim kelimesine en çok bir kelime uzakta olmalıdır; "yalnız komşu takvim ayları için değişim hesapla"
     (Q05) ay kısıtıdır, kolon kısıtı değil.
     Ekip arkadaşlarının bu davranışı kilitleyen testleri değişmedi.
3. Takip turu aktif tabloyla karşılanmıyorsa ve bu turda hiç veri/aktif tablo işlemi yapılmadıysa, model sabit metinden önce
   **bir kez** geri gönderilir (`STALE_TABLE_NOTE`): hangi araçlarla veriyi çekeceği ya da tabloyu süzeceği söylenir. Bekleyen
   netleştirme sorusuna verilen kısa cevap bu kapsamda değildir. İkinci denemede de veri yoksa eski sabit metin korunur.
   Aynı durumda çağrı aşaması "anlatım" değil "araç" olur: `workspace_show` veri üreten araç sayıldığı için ajan araçsız
   anlatıma geçiyor, model yeni kaynağı ekleyemiyordu (F03'ün üç tekrarında da; canlı izde ikinci çağrıya 0 araç sunuldu).
4. `AnalysisWorkspace.generation` tablo yeniden kurulunca (set_table, replace_table, revert) artar, kolon eklemede değişmez.
   Aktif tabloya bağlı araçların (workspace_*, analitik, grafik) döngü kilidi imzası bu kuşağı içerir: aynı çağrı yeni tabloda
   serbest, aynı tabloda yine kilitli.

## Sonuçlar
- Kullanıcı tablosu, ajanın kurduğu doğru tabloya yaklaşır; "hesapla" diyen kullanıcı kaynak kolonunu kaybetmez.
- Niyet sınıflandırması hâlâ anahtar kelime temelli; bu karar yalnız ölçülmüş yanlış pozitifleri kapatır. Genel çözüm
  (yapısal niyet çıkarımı) kapsam dışı.
- Takip turunda modele bir tur daha harcanır; tur limiti aşılmaz (yalnız `i < max_steps` iken).

## Ölçüm (23 Eylül)
Aynı puanlayıcılar, 71 vaka, 3 tekrar, sayısal kısım ham tabloyla:

| Koşu | Ortalama | PASS / PARTIAL / FAIL |
|---|---|---|
| ADR-0104 | 60,9 | 19 / 22 / 30 |
| ADR-0105 | 65,9 | 25 / 24 / 22 |
| Son hâl (bu ADR öncesi) | 67,4 | 25 / 26 / 20 |

Son hâlde kullanıcı tablosuyla puanlanınca ortalama 64,1. Aile bazında (ADR-0105 → son hâl):

| Aile | Değişim |
|---|---|
| A | 72,8 → 76,6 |
| C | 40,0 → 47,2 |
| I | 66,7 → 77,8 |
| Q | 75,3 → 77,3 |
| S | 71,0 → 73,4 |
| T | 83,9 → 77,2 (T06 kilit bulgusu, madde 4) |
| D | 53,6 → 52,1 |
| L | 53,9 → 56,5 |

Bu ADR'nin düzeltmeleriyle hedefli koşular (`v2_deepseek_final_fix*_r3_20260923*`, 3'er tekrar, kullanıcı tablosu):

| Vaka | Önce | Sonra | Madde |
|---|---|---|---|
| F08 | 40 | 100 | 1, 2 |
| T05 | 45 | 95 | 2 |
| F07 | 49 | 84 | 2 |
| Q05 | 66 | 100 | 2 |
| T06 | 46 | 84 | 4 |
| F03 | 38 | 100 | 3 |
| F01 | 17 | 46 | 3 (kalan kayıp ilk turda: veri yerine kapsam özeti) |

Davranış vakalarında O04 +29, F06 +19. S06 ve D08 düştü; D08'de ikinci turda `gold_align` aktif tabloyu eziyor (açık bulgu).
Son tam koşunun bu vakalarını hedefli koşularla değiştiren bileşik tahmin 64,1 → 69,4 (PASS/PARTIAL/FAIL 26/28/17). Farklı
kod sürümlerini birleştirdiği için tam koşunun yerine geçmez.
