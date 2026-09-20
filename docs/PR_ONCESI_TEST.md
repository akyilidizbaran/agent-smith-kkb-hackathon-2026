# PR test doğrulaması

GitHub Actions yeniden kullanılabilir durumda. Aşağıdaki workflow'lar PR açıldığında, `main`'e merge sonrası ve elle `workflow_dispatch` ile çalışır:

- `.github/workflows/tests-agent.yml`: `agent-core` birim ve sözleşme testleri
- `.github/workflows/tests-lakehouse.yml`: `lakehouse-core` testleri; A–H olarak paralel parçalanır

Lakehouse testleri 6.304 serilik katalogda 60 dakikalık job sınırına yaklaşabildiğinden test dizinleri sekiz parçaya dağıtılır. Her test dizini workflow içindeki bir parçaya açıkça atanır; yeni bir test dizini eklenirse ilgili `SHARD_*` listesine eklenmelidir.

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

## 21 Eylül 2026 CI zaman aşımı incelemesi

- PR/head `7d0009e` için Actions koşusu `35538510918` assertion hatası göstermedi. Lakehouse A ve C job'ları 60 dakikada kesildi; A son logda %29, C %62 ilerlemişti. B tamamlandı fakat süre sınırına yakındı. Bu bir kod/test başarısızlığı değil, eski üçlü parça dağılımının 6.304 serilik katalogda artık dengeli olmamasıdır.
- Workflow A–H olarak yeniden bölündü ve sonraki yeşil koşuda yavaş testleri görünür kılmak için `--durations=20` eklendi. Yeni dağılımın gerçek GitHub süresi henüz ölçülmedi; güncel head'e push/PR koşusu gerekir.
- Ayrıca katalog değişmediyse ilişki grafiği satırları tekrar yazılmıyor; yazılacak ilişkiler tek hazırlanmış DuckDB batch statement ile upsert ediliyor. Katalog bootstrap/regresyon testleri **22 geçti**, acceptance grubu **37 geçti**. Tam lakehouse paketi bu değişikliklerle tamamlanmadı.

## Conflict çözümünün test kapsamı

`main` ile birleştirme sırasında şu kararlar uygulandı:

- PR #9'daki 4.536 serilik FinTürk kataloğu korundu; o tarihteki üç parçalı Actions dağılımı 21 Eylül ölçümünden sonra A–H olarak yenilendi.
- `ingestion_registry.py`, PR #9'un tablo eşleme haritasını korurken gelecekteki `<tabloNo>|<SEHIR>` bulk adres biçimini de destekleyecek şekilde birleştirildi.
- Agent/lakehouse workflow'larında PR tetikleyicileri ve `main` push tetikleyicileri korundu.
- Bu belge, yerel test ölçümlerini ve Actions'ın merge kapısı olduğunu birlikte kaydeder.
