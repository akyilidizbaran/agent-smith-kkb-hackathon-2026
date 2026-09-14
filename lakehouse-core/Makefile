# Veri çekirdeği komutları (M15-T10). Eski "build" yalnız dizin açıyordu, "demo-check" iki eski sözleşme testiydi;
# adlar artık yaptıkları işi söylüyor. Canlı veri kurulumu repo kökünden: make demo-data.
.PHONY: test test-fast bootstrap silver gold

test:        ## tam test paketi (~13 dk)
	uv run --frozen pytest -q

test-fast:   ## sözleşme + betik + Silver kurulum testleri (dakikalar değil saniyeler)
	uv run --frozen pytest -q tests/contract tests/scripts tests/silver/test_build.py tests/catalog

bootstrap:   ## DuckDB şemaları ve katalog (DATA_ROOT/lakehouse.duckdb)
	uv run python -m lakehouse bootstrap

silver:      ## Bronze'dan Silver'ı yeniden kur
	uv run python -m lakehouse silver

gold:        ## incelenmiş Gold metriklerini üret
	uv run python -m lakehouse gold
