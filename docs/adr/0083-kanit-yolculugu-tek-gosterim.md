# ADR-0083: Kanıt yolculuğu tek gösterim — kanıttaki halkalar durak, her tür kendi figürüyle; 3B kaldırıldı

**Durum:** Kabul edildi · **Tarih:** 2026-09-15 · **Yerine geçtiği:** [ADR-0047](0047-kanit-yolculugu-iki-gosterim.md) (deneme, M14-T12)

## Bağlam
ADR-0047 kanıt yolculuğunu karar için iki gösterimle koymuştu: 2,5B SVG üstünde yürüyen karakter ve 3B three.js.
Kullanıcı 15 Eylül'de 3B'yi ve karakteri kaldırmaya karar verdi. Verdiği yatay zincir görseli (Cevap → Tablo → SQL → Silver →
Bronze → RAW → Kaynak URL) örnek alındı; tıklanabilir tasarım prototipi gerçek bir kayıtla (Adana konut kredisi, BDDK FinTürk)
hazırlandı ve onaylandı. Kullanıcının notu: yedi durak kalıp değil, kanıt grafiğinde hangi halkalar varsa onlar durak olur.
İlk uygulamada sıra görseldeki gibi cevaptan kaynağa gidiyordu. Kullanıcı ekranda görünce cevabın en sonda olması gerektiğini
söyledi: yolculuk verinin akışını anlatır, kaynaktan başlar ve cevapta biter.

## Karar
1. **Durak kurucusu `journeyStops(kanıt, sayı)`** (`static/index.html`). `sayı` cevaptaki bir sayının sırası ya da `null`
   (bütün cevap). Kurucu cevaptan kaynağa doğru iner, döndürdüğü sıra verinin akışıdır: kaynak → … → Cevap. Halkalar yalnız
   kanıtta varsa eklenir (aşağıda iniş sırasıyla):
   - Cevap (her zaman), Tablo (kolon izi varsa; yoksa kopuk);
   - SQL (web tablosu değilse; sorgu izi olmayan kolon kopuk);
   - Hesaplanmış tablo (kolon kaynağı `gold` ise);
   - Silver → Bronze → RAW → Kaynak URL/dosya (gözlem varsa). Sayının gözlemi önce değerden, sonra satır dönemiyle seçilir;
   - Web sayfası ya da Belge (OCR) → Kaynak URL (gözlem yok, web kaynağı varsa);
   - gözlem de web kaynağı da yoksa "gözlem izi yok" kopuk halkası.
2. **Durumlar:** doğrulandı (teal), uyarı (amber rozet: işaret/dönem uyarısı, OCR tahmini), kopuk (kırmızı üçgen),
   doğrulanamadı (kopuk halkadan sonrası gri), sırası gelmedi. RAW'da dosya yoksa, özet uyuşmuyorsa ya da özet
   denetlenmemişse halka kopuktur. Bu, kanıt panelindeki "dosya zinciri" ölçüsüyle aynıdır (D06-T03).
3. **Hareket:** animasyon kaynaktan başlar; bağlantılar sırayla dolar (640 ms), durak figürü dolma bitince belirir. İlk kopuk
   halkada durur, rozet belirir; ondan sonraki bağlantılar kesikli, duraklar (cevaba kadar) "doğrulanamadı" olur.
   `prefers-reduced-motion` açıkken son durum anında çizilir.
4. **Etkileşim:**
   - Sayı çipleri: "tüm cevap" ve her sayı; çip zinciri yeniden kurar ve oynatır.
   - Durağa tıklayınca ayrıntı kartı açılır: alanlar, sha256/çalıştırma için Kopyala, SQL, uyarı metni.
   - Önceki/Sonraki halka animasyonu durdurmaz.
   - Dar ekranda (≤720 px) zincir dikey akar, ayrıntı durağın altında açılır.
5. **Sağ panel:** aynı kurucudan küçük zincir (bütün cevap); tıklayınca yolculuk açılır.
6. **Kaldırılanlar:**
   - `static/vendor/three.module.min.js` (676 KB);
   - 2,5B/3B sekmeleri, yürüyen karakter, `requestAnimationFrame` döngüsü, eski `.stage`/`.bubble` stilleri.
7. **Katman adları:** Silver, Bronze ve RAW kanıt yolculuğunda kalır (ADR-0082: kullanıcıya dönük cevap metninde yok, kanıt
   zincirinde var). Her durağın altında düz dille alt başlık vardır (ör. "temizlenmiş gözlem").

## Sonuçlar
- Yolculuk kütüphanesiz; demo çevrimdışı çalışır, statik dosyalar 676 KB hafifler.
- Kanıt yükündeki gözlemler 12 ile sınırlıdır (`evidence_to_dict`). Bütün cevap zinciri bu 12 gözlemi denetler; Silver
  ayrıntısında "gösterilen 12 / N" yazar.
- Yeni halka türü eklemek için üç yer değişir: `JFIG` (figür), `JMETA` (ad, alt başlık, kısa etiket) ve kurucuda bir dal.
- Testler:
  - `tests/test_kanit_yolculugu.py`: durak kurucusunu gerçek kanıt şekilleriyle node üzerinde koşturur (tam zincir, RAW eksik,
    OCR belgesi, hesaplanmış tablo, tabloda olmayan sayı); node yoksa bu testler atlanır. Ayrıca 3B/karakter kalıntısı
    olmadığını ve her türün figürü olduğunu denetler.
  - `tests/test_web_app.py`: three.js dosyasının artık servis edilmediğini denetler.

## Ek (16 Eylül)
Kullanıcı cevaptaki sayıların pencerede çip olarak gösterilmesini istemedi. "Cevaptaki sayılar" satırı kaldırıldı; yolculuk her
zaman bütün cevabın zincirini gösterir (`journeyStops(kanıt, null)`). Kurucu tek sayı parametresini korur; testler tek sayının
zincirini de denetler (değer ve dönemle gözlem seçimi).
