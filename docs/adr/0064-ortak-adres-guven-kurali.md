# ADR-0064 — Ortak adres güven kuralı: ajan ile lakehouse bağlayıcısı aynı vakalarla sınanır

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Milestone:** M05-T03 (A19)

## Bağlam

Dışarıdan veri çeken üç yol vardı: ajanın web getirmesi (`web.fetch.private_host`), ajanın dosya okuyucusu
(`builder.read._private_host`, aynı kodun kopyası) ve lakehouse generic bağlayıcısı (`assert_url_is_allowed`).
Karşılaştırınca ölçülen ayrışmalar:

- Ajan tarafı yalnız private/loopback/link-local/reserved adreslere bakıyordu; çoklu yayın (224.0.0.1, ff02::1),
  site-local (fec0::/10) ve `.internal`/`.localhost` adları lakehouse'ta reddedilirken ajanda geçiyordu.
- IPv4-eşlemeli IPv6 (`::ffff:127.0.0.1`) Python 3.12 yamalarına göre "loopback" ya da "private" etiketleniyordu;
  GitHub koşucusunda lakehouse testi bu yüzden düştü.

## Karar

- Ajanda tek modül `kkb_agent/web/addresses.py` (`blocked_address`, `blocked_host`): IPv4-eşlemeli adres önce açılır;
  loopback, private, link-local, multicast, reserved, unspecified, site-local ve `localhost`/`*.localhost`/`*.internal`/
  `metadata.google.internal` reddedilir. Web getirme ve dosya okuyucu bu modülü kullanır (kopya kod kalktı).
- Lakehouse sınıflandırması da eşlemeli adresi önce açar (yorumlayıcıdan bağımsız etiket).
- Vakalar tek yerde: `docs/sozlesmeler/url_erisim_vakalari.json` (17 adres, 5 ad). İki paketin testi bu dosyayı okur
  (`agent-core/tests/test_m05_ortak_vakalar.py`, `lakehouse-core/tests/generic/test_shared_url_cases.py`); vaka eklemek iki
  tarafı birden sınar. Etiket belgedir, karşılaştırılan yalnız karar (ret/izin).

## Reddedilenler

- **Ajanın lakehouse paketini import etmesi:** ayrı sanal ortamlar ve bağımlılık yönü (ADR-0001 sözleşme ayrımı) bozulurdu.
- **Etiketleri de karşılaştırmak:** CPython yamaları eşlemeli adreste ayrışıyor; güvenlik kararı etikete bağlı değildir.

## Bilinen sınır

DNS yeniden bağlama (kontrol anında genel, bağlantı anında özel adres) iki tarafta da kapalı değil; bağlantının doğrulanan
adrese sabitlenmesi gerekir. Yönlendirme sekmeleri her iki tarafta yeniden doğrulanır (ADR-0051).
