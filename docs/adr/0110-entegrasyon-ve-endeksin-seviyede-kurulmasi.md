# ADR-0110: Açık PR'ların entegrasyonu ve taban ayı endeksinin seviyede kurulması

**Durum:** Kabul edildi · **Tarih:** 2026-09-23 · **İlgili:** ADR-0104, ADR-0108, ADR-0109, PR #21, PR #23, PR #27

## Bağlam
Üç açık PR aynı eski main'den (`28f96b7`) ayrılmıştı ve bu dalla aynı yerlere dokunuyordu:
- **PR #27 (Büşra):** dışa aktarım önsözü, PDF tabloları (pdfplumber), `value_column` ile kolon seçimi.
- **PR #23 (Elif):** web geri dönüşü, dinamik kaynaklar için isteğe bağlı gerçek Chrome katmanı, güvenli ay birleştirmesi.
- **PR #21 (Zümral):** veri alımı sertleştirme, tamamlanma sözleşmesi, `.xls`, vade dilimi katalog girişleri.

Dosya okumada aynı iş dört kez yazılmıştı (başlık/önsöz tespiti). Katalogda 18 vade dilimi kimliği iki kez tanımlıydı.

Gerçek modelle çok turlu uçtan uca koşuda ayrıca iki sorun görüldü:
1. **Endeks akım sütununda kuruldu:** "Tutarları taban ayına göre (=100) endeksle" isteğinde model endeksi SQL ile aylık hareket (akım) sütunlarında kurdu. Taban ayı negatif olunca endeksin işareti döndü.
2. **Panel engellendi:** Aynı istek "enflasyondan arındır" da dediği için tablo koruma kuralı (ADR-0108 madde 7) seviyeleri getirecek paneli engelliyordu. Endekse yol kalmıyordu.

## Karar
1. **Tek okuma motoru.** CSV/XLSX başlık tespiti PR #26 ayrıştırıcısında (`builder/tabular.py`) kalır. Başlıktan önce atlanan satırlar `attrs["preamble"]` olarak taşınır ve kayıt kartına not düşülür. Izgara yardımcıları (`frame_from_grid`) PDF tabloları için korunur. `.xls` yalnız xlrd ile okunur.
2. **Kayıt akışı PR #21'in akışıdır:**
   - beyan kapısı önce gelir;
   - alttaki "Toplam" satırı atılır;
   - aralıklı dönemler tarihe çevrilir;
   - PDF önce metin katmanından okunur.

   PR #27'den korunanlar:
   - önsöz notu;
   - "her çağrı tek seri" kuralı;
   - kolon adının seri anahtarına girmesi (aynı dosyadan iki kolon çakışmasın);
   - PDF okuyucu eksikse uyarı;
   - veriyle örtüşen beyanın sorulmaması (bunun için beyan kapısından önce hafif bir ön profil çıkarılır).
3. **Yeni kaynak mevcut tabloyu ezmez.** Zenginleştirme önce normalizasyonla (PR #26), olmazsa aylık tarih birleştirmesiyle (PR #23) denenir. İkisi de olmazsa mevcut tablo korunur ve JOIN_MISMATCH döner.
4. **Katalogda kimlik başına tek giriş.** Üreticiden gelen giriş kalır. PR #21'in elle doğrulaması benimsenir; 18 vade dilimi `verified` olur. Tek bir kovaya verilmiş grup adı takma ad olarak çıkarılır; o grup birden çok kovanın toplamıdır ve panelde kurulur.
5. **Tur niyeti tek yerde kalır (ADR-0104).** PR #21'in yeni yetenekleri `classify` mimarisine eklenir:
   - terfi ve kayıt;
   - yazma turunda teslim kısa devresinin atlanması;
   - SQL JOIN'in birleştirme sayılması;
   - liste isteğinde geniş arama.
6. **Doğrulanmış eşdeğer varsa Gold reddi turu bitirmez.** "Tekrar denemeyle çözülmez" kapanış satırı bu durumda çıkarılır. `gold_join` reddi yine panele yönlendirir.
7. **Taban ayı endeksi yalnız pozitif seviyede kurulur:**
   - **Hesap aracı:** `workspace_compute_column`, sıfır ya da negatif değer taşıyan bir sütunda endeks formülünü (`FIRST_VALUE(...) … * 100`) reddeder ve doğru yolu söyler. Ret yönlendiricidir, turu bitirmez.
   - **Panel:** Aynı kuralı kendi endeks döngüsünde uygular.
8. **Endeks isteği bir yetenektir.** "YYYY-AA=100" isteği `lakehouse_breakdown_panel` çağrısını gerektirir. `index_base` ya da `join_session` taşıyan panel çağrısı tablo korumasına takılmaz; önceki tablo ay üzerinden taşınır.
9. **Oturum birleştirmesi seçicidir:**
   - kanıt sütunları (`::observations` …) alınmaz;
   - tabloda zaten olan sütun tekrar eklenmez (`k1_`/`k3_` kopyaları yok);
   - katalog serisi tutar değilse (oran, kur) eklenir ama reel yapılmaz ve endekslenmez.

## Sonuçlar
- **Gerçek koşu:** Aynı tur dizisi, entegrasyondan sonra gerçek modelle defalarca koşuldu:
  - İlk üç tur her tekrarda beklenen değerleri verdi. Süreler 7–13 sn'ye indi (önce 60–270 sn).
  - Yüklenen dosyayla zenginleştirme turunda kaynak değerleri her tekrarda tuttu.
  - Çok kaynaklı yorum turunda son tekrar endeksi seviyede kurdu; kırılma analizi ve web araştırması yapıldı.
- **Açık:**
  - Çok kaynaklı yorum turu hâlâ modelin sırasına bağlı; cevapta kaynak sınırı (ör. işlem hacminin net akış olmadığı) her tekrarda yazılmıyor.
  - Zenginleştirme turunda önceki sütunların korunması tekrarlar arasında değişken.
- **Bağımlılıklar:** pdfplumber, playwright (sistem Chrome'u; tarayıcı indirmez), xlrd.
