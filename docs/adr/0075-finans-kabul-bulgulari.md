# ADR-0075 — Finans akışı bulguları: endeks baz güveni, üç ondalıklı sayı, grafik başlığı, bağlam kaynağı

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** düzeltme planı K02-T02…T05 (A02, A03, A05, A06, A07, A26)

## Bağlam

`scripts/k02_finans_kabul.py`, M16 canlı koşusunda modelin finans sorularına verdiği araç çağrılarını gerçek demo
lakehouse'ta, betikli modelle yeniden oynatır; beklenen değerler Silver'dan ayrı süreçte okunur. İlk koşular dört ürün
kusuru buldu:

- **KFE baz güveni (A05):** katalog `evds:TP.KFE.TR` için "baz yılı doğrulanmadı, reel dönüşümde kullanılmamalı" diyor
  (`semantic_confidence=derived`), ama `workspace_real_value` yalnız ölçüm tipine (index) bakıyordu: KFE ile reel değer
  sessizce üretilebiliyordu. `workspace_add_column` da eklenen kolonun birimini, dönem eşleşmesini ve anlam güvenini ne
  kartta ne kanıtta gösteriyordu.
- **Üç ondalıklı araç sayısı (A03/A06):** grounding araç çıktısındaki pandas ondalığı "18.388"i Türkçe binlik (18388)
  okuyordu. Gold aylık faiz değerleri çoğunlukla üç ondalıklı; modelin doğru yazdığı "%18,39" (hatta "%18,388") MISS sayılıp
  cevap geri gönderiliyor, sonunda deterministik çıkışa düşebiliyordu.
- **Grafik başlığı (A07/A26):** PNG ve kart başlığı birim ve dönemi taşıyordu; arayüze ve rapora giden artefakt başlığı
  yalnız konuyu taşıyordu.
- **Dış bağlam (A06):** `web_search` sonuçları kanıt panelinde ve raporda hiç görünmüyordu; cevapta kullanılan bağlamın
  kaynağı kayda geçmiyordu.

Yan bulgu: `workspace_add_column` anahtar normalizasyonu python `date` nesneli kolonda `AttributeError` veriyordu
(DuckDB DATE kolonu bunu gizliyordu).

## Karar

- **Anlam güveni sözleşmede:** `DatasetSpec.semantic_confidence` katalogdan taşınır. `workspace_real_value` doğrulanmamış
  endeksi `UNVERIFIED_SEMANTICS` ile reddeder ve doğrulanmış endeksleri aday verir. Rıza yalnız güncel mesajda ve Gold ile aynı
  sözcüklerle ("doğrulanmamış olsa da kullan", ADR-0068); rızayla kullanılırsa kart ve provenance uyarı taşır. Baz dönemin
  kapsam denetimi rızadan bağımsız sürer.
- **Sütun kartı:** `workspace_add_column` birim, ölçüm tipi, kaynak frekansı ve kapsamı, dönem eşleşmesini (m/n satır) ve
  endekste baz güvenini yazar. Doğrulanmamış anlam provenance uyarısı olur; kanıt kolonuna, XLSX uyarı sayfasına ve HTML
  rapora iner. Seri eklenebilir; yalnız baz yılına dayanan hesap rıza ister.
- **Grounding havuzu:** yalnız araç çıktılarında tek nokta + üç haneli sayı iki okumayla alınır (18,388 ve 18388). Cevap
  metni tek (Türkçe) okumayla ayrışır; çok gruplu sayı yalnız binliktir, "0.xxx" ondalıktır.
- **Grafik:** artefakt başlığı PNG'deki başlıktır (konu · birim · dönem); konu ayrı `topic` alanında.
- **Bağlam kaynağı:** `web_search` sonuçları `EvidencePanel.context_sources`'a "web araması — bağlam, veri değil" notuyla girer.
  Açılıp tabloya giren sayfa veri kaynağıdır (`web_sources`) ve bağlamdan çıkarılır. Panel metni, JSON, rapor "Kaynaklar" ve
  arayüz kanıt bölümü bağlamı veri kaynaklarından ayrı listeler; bağlamdan gelen sayı tabloyla eşleşmediği için doğrulanmış
  sayılmaz.

## Reddedilen seçenekler

- **KFE'yi tamamen kapatmak:** seri sorgulanabilir ve sütun olarak doğru biçimde eklenebilir; sorun yalnız baz yılına dayanan hesap.
- **Cevaba otomatik bağlam notu:** arama yapılıp sonucu kullanılmamış olabilir; not yanıltır. Kaynak kaydı ve "veri değil"
  etiketi deterministik; cevapta kaynağı anma kuralı istemde.
- **Grounding'i tablo hücrelerine genişletmek:** model önizlemede görmediği sayıyı araçtan almış olamaz; MISS doğru davranış.
  Betiğin ilk koşusu bunu gösterdi; canlı akıştaki gibi son ay `workspace_query` ile gösterildi.

## Sonuç

Testler: `tests/test_k02_kfe_denetimi.py`, `tests/test_k02_grounding_ondalik.py`, `tests/test_k02_baglam_kaynagi.py`;
ajan testleri 461 → 471. Kabul: `scripts/k02_finans_kabul.py` 22 denetim — 60 ay dönem ve değer, faiz hizalama değeri ve
görünürlüğü, dönem hesabı ve nedensellik geri gönderimi, dış bağlam kaynağı, reel değer, KFE ret/kapsam/kart/uyarı, grafik
PNG ve başlık, eski cevap raporları, demo DB değişmedi. Kanıt dosyası düzeltme planındaki K02 satırlarında.

Sınır: model betiklidir; canlı modelin aynı araç yolunu seçtiği M16 koşusunda görüldü, tekrar oranı K03 provasında ayrıca
ölçülür. Bağlam aramasında ağ sahtedir.
