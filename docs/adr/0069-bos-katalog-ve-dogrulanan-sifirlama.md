# ADR-0069 — Kalıcı boş katalog kipi ve doğrulanan tam sıfırlama

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** bağımsız kontrol R04/R05 → düzeltme D04/D05 (M03, M04, M16, A21c) ·
**Değiştirdiği:** ADR-0056 sıfırlama hedefleri ve bootstrap çağrısı

## Bağlam

- Arayüzün tam sıfırlaması sonrası çağrılan `lakehouse bootstrap` varsayılan finans kataloğunu yeniden yüklüyordu (yeni
  geçici DB'de 2.214 seri). Ingest, silver, gold ve promote komutları da önce bootstrap yaptığı için boş katalogla
  başlatılmış bir DB bile ilk komutta finans kataloğunu geri alırdı.
- Sıfırlama hedefleri sabit listeydi: `CHART_DIR` ve embedding önbelleği yoktu (`charts/old.png` kaldı). `rmtree(ignore_errors=True)`
  başarısız silmeyi gizliyor, hedef yine "silindi" listesine giriyordu.

## Karar

**Lakehouse (D04):**
- `meta.lakehouse_setting` tablosu; `series_catalog` = `default` | `none`. `bootstrap_database(catalog_mode=…)` kipi yazar;
  kip verilmeyen her sonraki bootstrap kayıtlı kipe uyar. Kip yoksa (eski DB) `default`.
- CLI: `python -m lakehouse bootstrap --catalog none|default`; çıktı `catalog_mode` satırını taşır. Kip satır silmez.
- Toplu finans ingest betiği boş katalog kipindeki DB'de açık hatayla durur.

**Ajan arayüzü (D04/D05):**
- Hedefler yapılandırmadan: DB ve WAL, `DATA_ROOT/raw|bronze|silver|quarantine`, `INGEST_ALLOWED_ROOT/uploads`,
  `CHART_DIR`, önbellek kökü. İzinli kökteki kullanıcı dosyaları (oturum yüklemesi olmayanlar) korunur.
- Veri kökü dışını gösteren bir ayar varsa önizlemede açıkça listelenir ve sıfırlama reddedilir; sessizce atlanmaz.
- Onay kodu hedef listesi, kök dışı ayarlar ve katalog seçimine bağlıdır; önizlemeden sonra kapsam değişirse 409 ve yeni önizleme.
- Varsayılan katalog seçimi **boş**; başlangıç kataloğunu yüklemek ayrı açık seçimdir.
- Yürütme oturum kilidi içinde: önce ajanın DuckDB okuyucuları kapatılır; her hedef için gerçek sonuç (`silindi`, `zaten yok`,
  `silinemedi` + sebep, `korunuyor`); silme sonrası yokluk denetlenir. Bootstrap hatası ve yeni DB'nin beklenen durumda
  olmaması (boş seçimde seri sayısı 0 ve kip `none`) başarı sayılmaz: genel durum `kısmi`.
- Oturum geçmişi, cevaplar, tablolar, yüklemeler temizlenir; oturum kimliği değişir; ajan yeni DB ile yeniden kurulur,
  kurulamazsa rapor bunu söyler.

## Reddedilenler

- **Sıfırlamadan sonra `meta.series`'i SQL ile boşaltmak:** sonraki bootstrap geri yükler; kip kalıcı olmalı.
- **Kök dışı hedefleri atlayıp "tam sıfırlandı" demek:** kapsam eksik kalır ve kullanıcı yanıltılır.

## Sonuç

Lakehouse `tests/catalog/test_catalog_mode.py` (kip silver/gold/promote/yeniden açılışta korunur, CLI bayrağı, eski DB);
ajan `tests/test_d05_sifirlama.py` (grafik/önbellek dahil kapsam, silinemeyen hedef, bootstrap hatası, dolu katalog, kök dışı ret,
uçtan uca önizleme → kod → sıfırlama). Arayüz penceresi kapsamı, katalog seçimini ve hedef hedef sonucu gösterir.
Gerçek CLI ile boş katalogdan finans dışı akış K01'de.
