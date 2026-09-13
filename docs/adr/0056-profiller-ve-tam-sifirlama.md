# ADR-0056: Analyst/Architect profilleri ve Architect'in açık onaylı tam sıfırlaması

**Durum:** Kabul edildi · **Tarih:** 2026-09-14 · **Milestone:** M04 · **Karar (K02, kullanıcı):** normal kullanıcı Analyst; kalıcı yazma/silme Architect; jüri iki profili de kullanır

## Bağlam
ADR-0039 yazmayı ayrı sürece ve taslak→onay akışına bağlamıştı; ama Architect araçları uygun ortamda
aynı kayıt defterine giriyordu, yani son kullanıcı ile ekip arasında profil sınırı yoktu. Kullanıcı
kararı: jüri Analyst'te dosya yükleyip analiz eder; Architect'e geçip tüm veriyi silip sıfırdan ya da
başka alan verisiyle kurabilir. Kimlik sistemi şart değil (tek bilgisayar, K07).

## Karar
1. **Profil başlatmada seçilir** (`AGENT_PROFILE=analyst|architect`, varsayılan analyst). Analyst
   kayıt defterinde `ingest_from_url` ve `promote_draft` **yoktur**; model adıyla çağırsa `UNKNOWN_TOOL`.
   Kapı (`tool_gate`) sunulan şemayı daraltır, yetkiyi değil (ADR-0043) — burada yetki yokluktur (T02/T03).
2. **Oturumda geçiş yalnız operatör anahtarıyla** (`ARCHITECT_TOKEN`; boşsa geçiş kapalı). İstek
   parametresi ya da sohbet metni yetki vermez; Architect'e geçiş oturumu temizler (A28).
3. **Tam sıfırlama iki adım, yalnız Architect** (`POST /api/architect/reset`): önce hedef listesi + onay
   kodu (listenin sha256'sı); sonra aynı kodla silme + `lakehouse bootstrap` (boş katalog). Hedefler
   yalnız DATA_ROOT altında: DB (+wal), raw, bronze, silver, quarantine, incoming/uploads, cache.
   Kod, kurulum dosyaları, `.env` ve sırlar listeye giremez (yol denetimi). Silme geri alınamaz; eski
   cevapların kanıt zinciri kopar, arayüz bunu söyler. Sonra yeni veri yüklendiğinde alan profili
   yeni kataloğa göre türetilir (ADR-0048).
4. **Pasifleştirme** (seriyi katalogda pasif bırakma, veri kalır) veri ekibinin CLI'ında yok; koşula
   bağlı (M04-T06 kısmi). Yayın talebi/inceleme arayüzü (T05) ihtiyaç doğarsa; mevcut taslak→açık
   onay akışı korunur.
5. Dosya/web içeriği veridir; adres ve yazma niyeti yalnız kullanıcı mesajından (A20 testi).

## Sonuçlar
- Testler 356 → 360. Canlı: Analyst'te yazma aracı yok; yanlış anahtar 403; Architect'e geçince
  ingest/terfi kayıt defterinde; sıfırlama planı listeyi verir, uygulanmadan hiçbir şey silinmez.
- Demo: `ARCHITECT_TOKEN` demo bilgisayarında .env'de; jüri önünde Baran girer. Sıfırlama demoda
  yalnız demo veri köküne uygulanır; ardından `make demo-data` ya da yeni dosya yüklemesi.
- ADR-0039'un "sohbetten terfi" ifadesi artık "Architect profilinde, sohbetten, açık onayla" olarak okunur.
