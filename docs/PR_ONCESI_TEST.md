# PR öncesi test — 18 Eylül 2026'dan itibaren

Repo 18 Eylül'de Pro hesaba taşındı; GitHub Actions yeniden açık (3.000 dk/ay). Testler PR açılınca ve
main'e merge sonrası **otomatik koşar**; bir PR ancak yeşilse merge edilir.

Kotayı korumak için koşu yalnız değişen pakette yapılır:

- **Ajan testleri** (`tests-agent`, ~1 dk): PR `agent-core/` içinde bir şey değiştirdiyse.
- **Veri testleri** (`tests-lakehouse`, 3 paralel parça, her biri ~15–25 dk): PR `lakehouse-core/` içinde bir
  şey değiştirdiyse. Toplam dakika tek işle aynı; parçalama 60 dk sınırına takılmamak için.
- Feature dalına push tek başına koşu başlatmaz; PR açık olmalı. Aynı dala yeni push eskisini iptal eder.

Bir dakika hesabı: veri PR'ı ≈ 45–70 dk, ajan PR'ı ≈ 1 dk. Ay sonuna kadar rahat; yine de deneme push'larını
azaltın, büyük veri değişikliklerini önce yerelde koşun.

## Yerelde koşmak (isteğe bağlı, veri tarafında tavsiye edilir)

`uv` kurulu olsun (CI de bunu kullanır; Python'u kendisi indirir): https://docs.astral.sh/uv/

Ajan tarafı, ~1 dk:

```
cd agent-core
uv sync --frozen --extra dev
uv run --frozen --extra dev pytest -q -p no:cacheprovider
```

Veri tarafı, tam paket, 30–70 dk (bilgisayara göre):

```
cd lakehouse-core
uv sync --frozen
uv run --frozen pytest -q -p no:cacheprovider
```

Veri tarafı, yalnız hızlı kısım, ~3 dk (katalog, script, sözleşme, güvenlik, parser; ara kontrol için):

```
cd lakehouse-core
uv run --frozen pytest -q -p no:cacheprovider tests/catalog tests/scripts tests/contract tests/security tests/parsers
```

## Windows'ta bilinen kırıklar (main'de de aynı, Linux CI'da geçiyor)

Yerelde Windows'ta koşarken bunlar sizin değişikliğinizden değildir. Bunların dışında kalan her kırık
değişiklikten kaynaklıdır.

| Paket | Test | Sebep |
|---|---|---|
| agent-core | `test_adim_yolculugu` (3), `test_kanit_yolculugu` (7) | `node -e` komut satırı Windows sınırını aşıyor (WinError 206) |
| agent-core | `test_evidence.py::test_adaptor_gozlemden_artifact_ve_raw_a_iner` | yol ayracı `/` bekleniyor |
| lakehouse-core | `tests/adhoc/test_end_to_end.py::test_local_csv_reaches_the_agent_through_the_adhoc_table` | `write_text` satır sonunu `\r\n` yapıyor, sha256 uyuşmuyor |
| lakehouse-core | `tests/contract/test_contracts.py::test_raw_path_is_deterministic_and_uses_the_contract` | yol ayracı |
| lakehouse-core | `tests/generic/test_connector.py::test_a_symlink_pointing_outside_the_root_is_refused` | Windows'ta symlink yetkisi |
| lakehouse-core | `tests/generic/test_connector.py::test_a_fifo_is_not_a_regular_file` | Windows'ta FIFO yok |

Beklenen Windows sonucu: agent-core **690 geçti, 11 kaldı**; lakehouse-core **1.122 geçti, 4 kaldı** (17 Eyl,
PR #9 dahil ağaçta ölçüldü).

## Yeni test dizini eklerken

`lakehouse-core/tests/` altına yeni bir dizin açılırsa `.github/workflows/tests-lakehouse.yml` içindeki
`SHARD_A/B/C` listelerinden birine yazılmalı; yoksa "Parça kapsamı" adımı kırılır ve PR kırmızı olur.
