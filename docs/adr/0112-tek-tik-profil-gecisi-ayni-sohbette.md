# ADR-0112: Tek tık profil geçişi, aynı sohbette

**Durum:** Kabul edildi · **Tarih:** 2026-09-23 · **İlgili:** ADR-0056 (2. maddenin yerine geçer), ADR-0084

## Bağlam
ADR-0056'ya göre profil başlatmada seçiliyordu. Oturumda geçiş yalnız operatör anahtarıyla (`ARCHITECT_TOKEN`) bir
pencereden yapılıyordu ve **geçiş yeni bir sohbet açıyordu**. Demoda bu iki sorun çıkardı:

1. **Geçiş kapalıydı.** Anahtar tanımlı değildi; profil değiştirmek için sunucuyu yeniden başlatmak gerekiyordu.
2. **Tablolar kayboluyordu.** Analyst'te yapılan analizden sonra dosyayı havuza kaydetmek için Architect'e geçilince
   tablolar ve geçmiş kayboluyordu. Kayıt aracının eklemesi gereken "mevcut tablo" artık yoktu.

A28 gereksiniminin (havuzu boşaltıp başka alanla çalışmak) karşılığı tam sıfırlamadır. Tam sıfırlama sohbeti hâlâ
temizler; profil geçişinin sohbeti temizlemesi bu gereksinim için gerekli değildir.

## Karar
1. **Arayüzde iki düğme.** Üst çubukta **Analyst | Architect** düğmeleri durur; tıklanan profile hemen geçilir.
2. **Geçiş aynı sohbette olur.** Ajan yeni profille yeniden kurulur, ama sohbetin durumu yeni ajana taşınır: çalışma
   tablosu, önceki tablolar, konuşma geçmişi, takip bağlamı ve yüklemeler. Sohbet açma ile profil geçişi aynı yardımcıyı
   kullanır: `Session._apply_agent_state`.
3. **Yetki istek parametresinden gelmez**; operatörün ayarından gelir (`PROFILE_SWITCH`):
   - `token` (varsayılan): Architect'e geçiş `ARCHITECT_TOKEN` ister. Arayüz anahtarı bir kez sorar ve o sekmede
     hatırlar; sonraki geçişler tek tıktır.
   - `open`: anahtarsız tek tık. Yalnız güvenilen demo ortamı içindir.
   - Anahtar da `open` da yoksa Architect düğmesi kapalıdır ve nedeni ipucunda yazılır.
   - Analyst'e (salt-okunur) dönüş her zaman serbesttir.
4. **Tam sıfırlama ayrı korunur.** Yalnız Architect'te çalışır; iki adımlı onay kodu ister; hedefler yalnız `DATA_ROOT`
   altındadır (ADR-0056/0069).
5. **Durum arayüze bildirilir.** `/api/status` geçiş kipini `profile_switch_mode` alanında döner: `open`, `token` ya da
   `closed`.

## Sonuçlar
- **Demo akışı kesilmiyor.** Analiz Analyst'te yapılır; "havuza ekle" için Architect'e geçilir; aynı tabloya eklenir.
- **Testler:**
  - Anahtarlı geçiş sohbeti koruyor.
  - Açık kipte tek tık geçiş tabloyu yeni ajana taşıyor.
  - Kapalı kipte Architect'e geçiş reddediliyor.
- **Tarayıcıda denendi.** Architect → Analyst → Architect: 8 cevaplık sohbet ekranda ve sunucuda korundu. Kayıt araçları
  profile göre gelip gitti.
- **Risk:** `open` kipinde, arayüze erişebilen herkes Architect'e geçebilir. Herkese açık bir adreste `token` kipi
  kullanılmalıdır.
