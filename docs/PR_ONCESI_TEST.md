# PR test doğrulaması

GitHub Actions yeniden kullanılabilir durumda. Aşağıdaki iki workflow hem `pull_request` açıldığında hem de `workflow_dispatch` ile elle çalışır:

- `.github/workflows/tests-agent.yml`: `agent-core` birim ve sözleşme testleri
- `.github/workflows/tests-lakehouse.yml`: `lakehouse-core` tam test paketi

Merge kararı GitHub Actions sonucuna dayanır. Yerel sonuçlar bu dosyada yalnızca iz bırakmak ve PR gövdesine ölçüm koymak için tutulur.

## CI ile aynı yerel komutlar

```bash
cd agent-core
uv sync --frozen --extra dev
uv run --frozen --extra dev pytest -q -p no:cacheprovider

cd ../lakehouse-core
uv sync --frozen
uv run --frozen pytest -q -p no:cacheprovider
```

## 18 Eylül 2026 yerel doğrulama

- `agent-core`: **801 geçti**, 1 Starlette deprecation uyarısı, **6,71 s**.
- `lakehouse-core` hızlı hedefli kapsam (katalog ilişkileri, FinTürk parser, Silver build, DB altyapısı ve catalog bootstrap): **55 geçti**, **142,58 s**.
- `lakehouse-core` tam paket: CI ile aynı komut yerelde başlatıldı; 6.304 serilik katalog bootstrap maliyeti nedeniyle yaklaşık 14 dakika sonra %6 ilerlemede durduruldu. Bu koşuda assertion/test hatası görülmedi; tam paket sonucu PR açıldıktan sonra `tests-lakehouse` Actions job’ının otoritatif sonucudur.
- `git diff --check`: başarılı.
- `.env`: değiştirilmedi; SHA-256 `3d9edab0b35a33c3c0b99c4e1dec457f54d8cc8abe03ba160ddcced59d74e516`.

PR gövdesine yazılacak kısa satır:

```text
Tests: agent-core 801 passed locally; lakehouse targeted 55 passed. Full lakehouse suite is enabled in GitHub Actions and is the merge gate because the 6,304-series catalog bootstrap is too slow for the local quick loop.
```
