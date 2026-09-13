# ADR-0044: Arayüz — ajanı saran ince katman, kanıt ve iz önde

**Durum:** Kabul edildi · **Tarih:** 2026-09-13 · **Sıradaki:** E kapanış (motor kararı, main birleştirme, freeze)

## Bağlam
Ajan CLI'da çalışıyor; jüri demo günü canlı PDF verecek ve cevabın nereden geldiğini görmek
isteyecek. Harness'in asıl değeri (kanıt zinciri, guard'lar, araç izi, bütçe) terminal
çıktısında kayboluyor. Arayüz için üç yön taslak olarak çizildi (Claude Design kanvası,
`docs/design/`): A editoryal veri-önce, B terminal yoğunluğu, C rapor-önce. Kural: arayüz yeni
mantık taşımaz; ajan neyi üretiyorsa onu gösterir.

## Karar
1. **İnce katman.** `kkb_agent/web_app.py` FastAPI: `POST /api/ask` ajanın `AgentAnswer`
   nesnesini olduğu gibi JSON'a çevirir (metin, adımlar rol/araç/hata/süre, aktif tablo ilk 200
   satır, grafik PNG base64, kanıt paneli, token kullanımı, araç kapısı kararı, kalan arama
   bütçesi). `GET /api/status` katalog/yüklü/Silver/Gold sayılarını canlı DB'den okur.
   `POST /api/reset` ajanı yeniden kurar. Ajan `build_agent` ile bir kez kurulur; sorular
   kilitle sıralıdır çünkü tek workspace taşır. `create_app(agent_factory)` testte sahte ajan
   alır; ağ yok. Başlatma: `python -m kkb_agent.serve` (`kkb_agent.web` paketi web araçlarına ait).
2. **Yön A seçildi (ana ekran):** üç sütun. Sol: veri havuzu sayıları + oturum. Orta: soru,
   cevap (küçük ve kaçırılmış Markdown: paragraf, kalın, madde, boru tablosu), aktif tablo ile
   grafik yan yana, altta araç izi (rol · araç · hata kodu · süre) ve soru kutusu. Sağ: kanıt
   zinciri — "tam" / "EKSİK" rozeti, cevaptaki sayılar (eşleşen yeşil, eşleşmeyen kehribar),
   kolon → SQL, Silver gözlemi → artifact/Bronze/RAW → kaynak, belge (OCR) halkası kehribar,
   kopuk halkalar ve danışılıp kullanılmayanlar ayrı notlarda. Tek `static/index.html`,
   çerçeve yok, CDN yok (yalnız Google Fonts; yoksa sistem yazı tipi).
3. **Gizleme yok.** Guard notları, "OCR ile okundu, doğrulanmadı", adım sınırı, kapalı araçlar
   ve kalan bütçe ekranda. Grafik altına sabit not: belirtim araçta kuruldu, denetçiden geçti.
4. **Tasarım dosyaları repoda** (`docs/design/*.dc.html`, `canvas.json`); seed edilmiş kanvas
   (2,5 MB) repoya girmez, yalnız yayınlanan bağlantı PROJECT_MEMORY'de.

## Sonuçlar
- Arayüz için ayrı test: sahte ajanla durum → soru → sıfırlama döngüsü, NaN ve 200 satır kırpma.
- Demo DB'de `/api/status`: 2.214 katalog · 127 yüklü · 8.290 Silver · 6 Gold (tasarımdaki
  sayılarla birebir).
- Sınır: tek oturum, kimlik yok (yerel demo). Akış (streaming) yok; ajan bitince tek cevap.
  İstenirse SSE ile adım adım iz sonraki adım.
- Reddedilenler: React/Vite (freeze'e 7 gün, derleme adımı riski); chat geçmişini sunucuda
  saklama (ajanın workspace'i zaten oturumu taşıyor); Streamlit (kanıt paneli düzeni kurulamıyor).
