# ADR-0051: Web erişim sınırı — yönlendirme sekme sekme doğrulanır, robots aynı sınırdan

**Durum:** Kabul edildi · **Tarih:** 2026-09-13 · **Milestone:** M05

## Bağlam
Ölçüldü: `fetch_url` yalnız ilk hostu kontrol edip `allow_redirects=True` ile kütüphaneye
bırakıyordu; sahte taşımayla public URL → `http://127.0.0.1:9999/private` son URL olarak kabul
edildi. `robots.txt` isteği de otomatik yönlendirmeliydi. Veri ekibinin generic connector'ı her
sekmeyi doğruluyor; iki katman ayrışmıştı.

## Karar
1. **Kendi yönlendirme döngümüz** (`guarded_get`): kütüphane takibi kapalı; her `Location` hedefi
   istekten önce şema + özel/loopback adres kontrolünden geçer; en çok 5 sekme; döngü reddi; toplam
   süre sınırı (3 × istek zaman aşımı); yönlendirilen host için robots yeniden sorulur.
2. **Robots aynı sınırdan:** robots.txt de `guarded_get` ile; özel adrese yönlendirme takip edilmez,
   host `unreachable_hosts`'a yazılır (izinli sayılır, kanıt panelinde görünür); 512 KB sınır.
3. **Başlıklar başka hosta taşınmaz:** yalnız User-Agent/Accept geçer (kimlik bilgisi taşımıyoruz;
   ileride taşınırsa kural hazır).
4. **Yarım indirme:** akış okuma hatasında bağlantı kapanır, sonuç "erişilemedi" olarak döner;
   bayt sınırı aşımında da kapanır ve reddedilir.
5. Ret, ağ isteği yapılmadan ve sebep metniyle (`RedirectRefused`); araç bunu kullanıcıya olduğu
   gibi söyler.

## Sonuçlar
- Testler (`tests/test_m05_erisim.py`, sahte taşıma): A19 public→private, public→public, döngü,
  sekme sınırı, robots→özel, DNS hatası, yarım indirme, bayt sınırı, başlık taşınmaması. 338 → 344.
- Açık: veri ekibinin connector'ıyla ortak sözleşme testi (M05-T03); DNS sonucu ile bağlantı
  arasındaki yarış (DNS rebinding) çözülmedi, kapsam dışı yazıldı. "SSRF tamamen çözüldü" iddiası yok.
