# PR test doğrulaması

GitHub Actions yeniden kullanılabilir durumda. Aşağıdaki workflow'lar PR açıldığında, `main`'e merge sonrası ve elle `workflow_dispatch` ile çalışır:

- `.github/workflows/tests-agent.yml`: `agent-core` birim ve sözleşme testleri
- `.github/workflows/tests-lakehouse.yml`: `lakehouse-core` testleri; A/B/C olarak paralel parçalanır

Lakehouse parçaları, 6.304 serilik katalog bootstrap'ının tek job'da 60 dakika sınırına yaklaşmasını önler. Her test dizini workflow içindeki bir parçaya açıkça atanır; yeni bir test dizini eklenirse `SHARD_A/B/C` listelerine de eklenmelidir.

Merge kararı GitHub Actions sonucuna dayanır. Yerel sonuçlar iz bırakmak ve PR gövdesine ölçüm koymak için tutulur.

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

- `agent-core`: **802 geçti**, 1 Starlette deprecation uyarısı, **6,77 s**.
- `lakehouse-core` conflict sonrası hedefli kapsam (katalog, relation, ingestion registry, FinTürk parser/connector, Silver build ve catalog bootstrap): **131 geçti**, **261,69 s**.
- `lakehouse-core` tam paket: CI ile aynı komut yerelde başlatıldı; 6.304 serilik katalog bootstrap maliyeti nedeniyle yaklaşık 14 dakika sonra %6 ilerlemede durduruldu. Bu koşuda assertion/test hatası görülmedi; tam paket sonucu `tests-lakehouse` Actions işinin otoritatif sonucudur.
- `git diff --check`: başarılı.
- `.env`: değiştirilmedi; SHA-256 `3d9edab0b35a33c3c0b99c4e1dec457f54d8cc8abe03ba160ddcced59d74e516`.

## Conflict çözümünün test kapsamı

`main` ile birleştirme sırasında şu kararlar uygulandı:

- PR #9'daki 4.536 serilik FinTürk kataloğu ve üç parçalı lakehouse Actions yapısı korundu.
- `ingestion_registry.py`, PR #9'un tablo eşleme haritasını korurken gelecekteki `<tabloNo>|<SEHIR>` bulk adres biçimini de destekleyecek şekilde birleştirildi.
- Agent/lakehouse workflow'larında PR tetikleyicileri ve `main` push tetikleyicileri korundu.
- Bu belge, yerel test ölçümlerini ve Actions'ın merge kapısı olduğunu birlikte kaydeder.
