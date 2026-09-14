# ADR-0076 — Katalog sayacı onaylanmış adhoc seriyi sayar; uzak model anahtarı yoksa ön kontrol hazır demez

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** düzeltme planı K01-T07 (A21), K02-T01 (A01)

## Bağlam

- **K01-T07 arayüz provası:** tam sıfırlamadan sonra boş katalogda yeni alan kurulup `adhoc:web_ziyaret` onaylandı; DB'de tek
  aktif seri vardı ama `/api/status` ve kenar çubuğu katalog sayacı 0 gösterdi. Sayaç kaynağı `adhoc` olan bütün serileri
  dışarıda bırakıyordu; oysa onaylanan (aktif) adhoc seri kataloğun parçasıdır, yalnız taslak değildir.
- **K02-T01 kurulum provası:** temiz klonda `make preflight` "hazır" dedi (model satırında "anahtar yok" yazmasına rağmen),
  `make serve` ise ham `OpenAIError: Missing credentials` izleriyle çöktü. Provada `.env` kabukta `source` edilmişti:
  `MIA_API_KEY` satırındaki boşluk ve `LLM_API_KEY=${MIA_API_KEY}` referansı kabukta kayboluyor; python-dotenv ikisini de
  doğru okur. Ama `.env`'de anahtarın boş kalması da aynı sonucu verir: ön kontrol hazır diyor, arayüz başlamıyor.

## Karar

- Katalog ve yüklü seri sayaçları yalnız TASLAK adhoc serileri dışarıda bırakır. Onaylanan adhoc seri iki sayaçta da yer alır.
- `Settings.llm_key_missing`: model uç noktası yerel değilse (localhost/127.0.0.1 dışında) ve `LLM_API_KEY` boşsa doğrudur.
  Bu durumda ön kontrolün model satırı ✗ olur ve sebebi yazar ("uzak model için LLM_API_KEY boş: arayüz başlamaz").
  Ajan kurulumu ham istemci hatası yerine açık mesajla durur.
- Operasyon tarifi: `.env` uygulamaca okunur; kabukta `source .env` yapılmaz.

## Reddedilen seçenekler

- **Taslakları da katalog sayacına katmak:** taslak onaylanmamış veridir; sayaç ortak kataloğu anlatır.
- **Uzak modelde yer tutucu anahtarla başlatmak:** arayüz açılır, hata ilk soruda gelir; ön kontrolün amacı bunu önceden söylemek.

## Sonuç

`tests/test_k02_kurulum_sayac.py` (uzak/yerel model ve boş/dolu anahtar; taslak ve onaylı adhoc sayacı). Arayüz kanıtı
`docs/experiments/k01_ui_kabul_2026-09-14_1319/rapor.json` (yeni alan adımında sayaçlar 1). Kurulum provası kanıtı düzeltme
planının K02-T01 satırında.
