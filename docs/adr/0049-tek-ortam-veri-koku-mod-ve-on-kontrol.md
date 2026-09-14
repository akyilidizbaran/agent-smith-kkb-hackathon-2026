# ADR-0049: Tek çalışma ortamı — repo içi lakehouse-core, DATA_ROOT, demo/seed modu, salt-okunur ön kontrol

**Durum:** Kabul edildi · **Tarih:** 2026-09-13 · **Milestone:** M01 · **Sıradaki:** M05/M13 düzeltmeleri, M02 kıyası

## Bağlam
Ölçüldü (13 Eylül incelemesi): ajan varsayılanları seed DB'ye bağlanıyor; `LAKEHOUSE_CORE_DIR`
varsayılanı (`../lakehouse-core`) yok, veri kodu geçici scratchpad worktree'sinde; bu yüzden
Architect araçları ve Gold açılmıyor, "çalışan demo" tek komutla görünür değil. Silver şeması
yoksa adaptör sessizce seed'e düşüyor: yanlış DB'yle demo yapılabilir.

## Karar
1. **Veri kodu repo ağacında.** `origin/feature/lakehouse-catalog-breadth:lakehouse-core` dizini
   `lakehouse-core/` altına ağaç anlık görüntüsü olarak alındı (`git read-tree --prefix`); tarihçe
   veri dalında kalır, sha `docs/M01_ORTAM.md`'de. Yenileme: `scripts/sync_lakehouse_core.sh`.
   Subtree/merge yerine anlık görüntü: iki tarihçe ortak atasız, main birleştirmesi M17'de ayrıca.
2. **DATA_ROOT.** Tüm veri yolları repo kökündeki `data/` altında (gitignore): DB, RAW/Bronze,
   incoming, charts, cache. Göreli yollar repo köküne göre çözülür. Kod dizini veri taşımaz.
3. **LAKEHOUSE_MODE = demo | seed | auto.** demo varsayılan; DB yok ya da şema seed ise açık nedenle
   durur ve kurma komutunu söyler. Sessiz düşüş yalnız `auto`'da (testler).
4. **Salt-okunur ön kontrol** `--preflight`: hiçbir şey indirmez/yazmaz; DB, şema, sayılar, tarih
   aralığı, gold, provenance, RAW/Bronze, lakehouse-core ve CLI'ın çalıştığı, izinli kök, model,
   anahtar var/yok. Veri değiştiren tek komut `scripts/build_demo_data.py` (`make demo-data`),
   silme yalnız `--fresh --yes` ve listeyle.
5. **Kök Makefile** tek giriş: setup, preflight, demo-data, serve, test.

## Sonuçlar
- `LAKEHOUSE_PATH=data/lakehouse.duckdb` artık repo kökünde çözülür; eski agent-core/data seed'i
  yalnız `LAKEHOUSE_MODE=seed` ile kullanılır.
- Kabul: temiz klondan `make setup → preflight (HAZIR DEĞİL, sebep) → demo-data → preflight (hazır)`.
- Sınır: ön kontrol MIA'yı yalnız `--live` ile dener; CLI kontrolü `--help` koşusudur, ingest denemez.
