# PR öncesi test — 17 Eylül 2026'dan itibaren

GitHub Actions'ın aylık kotası tükendi ve açılmayacak. Bu yüzden **hiçbir test GitHub'da otomatik
koşmuyor**. Değişikliği yapan kişi PR'dan önce testleri kendi bilgisayarında koşar ve sonucu PR gövdesine
tek satır yazar; review yapan kişi o satır yoksa merge etmez.

- **Ajan testleri** (`agent-core`, ~1 dk): agent-core'a dokunan her PR'da.
- **Veri testleri** (`lakehouse-core`, 30–40 dk): lakehouse-core'a dokunan her PR'da.

Testlerin kendisi değişmedi; yalnız nerede koştukları değişti. Kota bir gün açılırsa
`.github/workflows/tests-agent.yml` ve `tests-lakehouse.yml` içindeki yorumlu `pull_request` blokları açılır.

## Kurulum (bir kez)

`uv` kurulu olsun (CI de bunu kullanır; Python'u kendisi indirir): https://docs.astral.sh/uv/

## Her PR'dan önce

Ajan tarafı, ~1 dk:

```
cd agent-core
uv sync --frozen --extra dev
uv run --frozen --extra dev pytest -q -p no:cacheprovider
```

Veri tarafı, tam paket, 30–40 dk (lakehouse-core'a dokunan her PR'da):

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

## PR gövdesine yazılacak satır

```
Testler (Windows, 17 Eyl): agent-core 690 geçti / 11 kaldı (bilinen); lakehouse-core 1.122 geçti / 4 kaldı (bilinen). Komut: tam paket.
```

## Windows'ta bilinen kırıklar (main'de de aynı, Linux'ta geçiyor)

Bunlar sizin değişikliğinizden değildir. Bunların dışında kalan her kırık değişiklikten kaynaklıdır.

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
