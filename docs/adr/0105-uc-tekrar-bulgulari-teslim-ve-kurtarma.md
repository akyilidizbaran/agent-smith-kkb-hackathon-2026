# ADR-0105: Üç tekrarlı benchmark bulguları: teslim, kurtarma ve açık seri

**Durum:** Kabul edildi · **Tarih:** 2026-09-23 · **İlgili:** ADR-0104

## Bağlam
ADR-0104 sonrası 71 vaka 3 tekrarla koşuldu (`v2_deepseek_adr0104_r3_20260923*`).

Puanlama:
- sayısal 27 vaka `score_v2.py` ile;
- 44 davranış ve politika vakası sözleşme rubriğiyle, aynı talimatla çalışan incelemecilerle.

Adil karşılaştırma için 23 Eylül koşusu da aynı puanlayıcılarla yeniden puanlandı: 61,5 → 60,9. Genel olarak yerinde saydık:
- **Kazananlar:** Q05 +83, O08 +42, I08, Q02, T07.
- **Kaybedenler:** özellikle A05, Q08 ve A08 politika vakaları.

Kök nedenler:
1. **Şablon teslim politika reddini ezdi.** ADR-0104'te CLARIFY_NOT_ALLOWED teslimi kapatmaz yapılınca, deterministik
   "İstenen veri tablosu hazırlandı" teslimi, "tabloları sil" ve "kişisel bilgileri ekle" isteklerindeki reddi yuttu.
2. **Eski tablo teslimi:** takip turunda yalnız `workspace_show` çalıştığında önceki turun tablosu "hazırlandı" diye teslim
   edildi. F03.2'de EVDS eklemesi, F01.2'de dönem kırpması yapılmamıştı.
3. **Sabit kapanış metinleri:**
   - Arama bütçesi ya da tekrar döngüsü, veri yokken sabit bir metinle kapandı; aday bulunmuş olsa bile "stok var, akış
     yok" tespiti yazılamadı (D01, T07, T08, P05, Q02, I07, O05).
   - Başarısız sorgu + "bulunmuyor" ifadesi varsa cevabın tamamı "doğrulayamadım" metniyle değiştirildi (R03).
4. **Tarih kolonu hatası:** Gold çıktısındaki `period_end` Python tarih nesnesidir; `workspace_compute_column` bunu metin sanıp
   ORDER BY'ı reddetti. T06, C02 ve C06'da INVALID_ARGS döngüsüne girildi.
5. **Açık seri kodu:** C04 ve C07 "EVDS TP.KTF12" dediği hâlde model aynı türde başka bir faiz serisini sessizce kullandı.

## Karar
1. CLARIFY_NOT_ALLOWED yine teslimi kapatan bir hata sayılır. Yalnız DUPLICATE_CALL ve CATALOG_SEARCH_BUDGET yürütülmemiş ret
   sayılır.
2. `TurnIntent.sensitive`: veri silme ya da değiştirme ve kişisel veri istekleri. Bu turlarda şablon tablo teslimi devreye
   girmez.
3. Takip turunda yalnız `workspace_show` çalıştıysa ve istek yeni bir şey içeriyorsa (birleştirme, dönüşüm, değişen
   dönem/kaynak/seri), tablo teslimi tamamlanmış sayılmaz.
4. Kapanış metinleri:
   - Arama bütçesi ya da tekrar döngüsünde aday bulunmuşsa sabit metin yok. Araçsız kurtarma çağrısı; notu bulunan adayları
     verir ve hangisinin uyduğunu, neyin eksik olduğunu ve sonraki adımı ister.
   - Başarısız sorgu sonrası yokluk ifadesi silinmez; "yalnız incelenen adaylara dayanır" notu eklenir.
5. Arama bütçesi 5'ten 8'e çıktı. DeepSeek'te arama 1–2 saniye; il bazlı sorular (R04) 3 il için ayrı arama istiyor.
6. `workspace_compute_column`: tarih nesnesi ya da ISO `YYYY-MM-DD` metin kolonu ORDER BY için geçerli; `31.01.2025` gibi
   biçimler reddedilmeye devam eder.
7. `lakehouse_query` politikası: soruda açıkça yazılan seri kodu (rakam ya da nokta içeren, en az 5 karakterli kod parçası)
   varken aynı kaynaktan aynı birim ve ölçüm türündeki başka bir seri okunamaz (SERIES_SEMANTIC_MISMATCH, aday: adı verilen
   seri). Farklı türdeki yardımcı seriler serbesttir (ör. reel dönüşüm için TÜFE).

## Sonuçlar
- Suite 976 geçti. Yeni testler: `tests/test_adr0105_teslim_ve_tarih.py` ve `test_tool_failure_recovery.py` ekleri.
- Niyet fikstürüne `sensitive` bayrağı eklendi; A05, A06, A08 ve Q08 kaydı gözden geçirildi.
- Etki, aynı 71 vakanın 3 tekrarıyla ve aynı puanlayıcılarla ölçülür (`v2_deepseek_adr0105_r3_20260923*`).

## Ölçüm (23 Eylül)
Aynı puanlayıcılarla, 71 vaka:

| Koşu | Ortalama | PASS / PARTIAL / FAIL |
|---|---|---|
| 23 Eylül (tek koşu) | 61,5 | 23 / 19 / 29 |
| ADR-0104 (3 tekrar) | 60,9 | 19 / 22 / 30 |
| ADR-0105 (3 tekrar) | 65,9 | 25 / 24 / 22 |

Tekrarlar 65,5 / 65,8 / 66,4.
- En çok artanlar: A05 +50, T08 +49, C04 +44, P05 +42, Q02 +38, T07 +37, D01 +36.
- Düşenler: Q01 −29 (anlatım satır sayısını değer gibi okudu), O04, T03, A07, P03.

## Ek: ikinci tur (aynı gün)
8. **Kapsam kapısı** (`_seri_secim_uyusmazligi`): yalnız pencereyi tam kapsayan bir alternatif varken reddeder. F01 "mevcut
   kapsamı ayrı raporla" dediği hâlde, alternatifi olmayan ihracat kredisi serisi her tekrarda reddediliyordu.
9. **Konuşma etiketi:** `resolve_follow_up` satır başındaki "Takip:", "İlk mesaj:" etiketini çözümlemeden önce ayıklar. F04'te
   "Takip:" "takip" ölçüsü sanılıyor, tur yeni veri isteği sayılıp takipteki alacak serileri seçiliyordu.
10. **`TurnIntent.absolute_and_percent`:** aynı turda hem mutlak fark hem yüzde değişim istenince tek işlemli deterministik
    hızlı yollar devreye girmez; önceden yalnız yüzde hesaplanıyordu.
11. **Benchmark koşucusu** (`run_v2.py`) `table` alanına kullanıcının gördüğü tabloyu yazar: `project_result_table`, arayüz ve
    CSV/XLSX ile aynı. Ham çalışma tablosu `workspace_table` olarak ayrıca kaydedilir.
    - Önceki koşular ham tabloyu puanlatıyordu. Kanıt kolonları (sha256, gözlem sayıları) "kullanıcı tablosuna karıştı" diye
      84 tavanına çarpıyordu (O01, O02, C04).
    - Adil karşılaştırma için `score_v2.py --table-key workspace_table` ham tabloyla da puanlar.
12. **Kullanıcı tablosunda kaynak kolonlar** (`web_app._compute_result_projection`). Hesaplama turunda kaynak kolonlar yalnız
    özel bir "hem orijinal hem değişim" kalıbıyla gösteriliyordu; soruda "yüzde" geçince mutlak fark kolonları da düşüyordu.
    11. madde kullanıcı tablosunu ölçünce ortaya çıktı: ham tabloyla 75,4, kullanıcı tablosuyla 63,6 (F02, F04, F07, L05, T05).
    - Kullanıcı kaynak veriyi de istiyorsa kaynak kolonlar gösterilir: bakiye, stok, seviye, nominal ya da orijinal adı geçiyor
      ya da mevcut tabloya "ekle" diyor.
    - Mutlak fark ve yüzde birlikte istenince ikisi de gösterilir.
    - "Aylık değişimleri göster" eskisi gibi yalnız değişimleri gösterir (ekibin 7 testi aynen geçiyor). "Yalnız/sadece değişim"
      her zaman kazanır.
