# Agent Smith — tek giriş noktası (M01, ADR-0049). Yollar .env ve DATA_ROOT ile; varsayılan repo/data.
.PHONY: setup preflight demo-data serve test test-data health ci

setup:            ## iki ortamı kilit dosyalarıyla kur (agent-core Python ≥3.11, lakehouse-core 3.12)
	cd agent-core && uv sync --frozen --extra dev
	cd lakehouse-core && uv sync --frozen

preflight:        ## salt-okunur ön kontrol: mod, DB, şema, veri, CLI, dizinler, anahtar var/yok
	cd agent-core && PYTHONPATH=src uv run python -m kkb_agent.cli --preflight

demo-data:        ## veri DEĞİŞTİRİR: bootstrap → canlı ingest (demo serileri) → silver → gold → fikstürler
	cd agent-core && uv run python scripts/build_demo_data.py

serve:            ## arayüz http://127.0.0.1:8765
	cd agent-core && PYTHONPATH=src uv run python -m kkb_agent.serve

health:           ## adaptör görünümü (ajanı kurar)
	cd agent-core && PYTHONPATH=src uv run python -m kkb_agent.cli --health

test:             ## agent birim testleri (deterministik, ağ yok)
	cd agent-core && uv run --frozen --extra dev pytest -q

test-data:        ## lakehouse testleri (~13 dk)
	cd lakehouse-core && uv run --frozen pytest -q

ci:               ## CI ile aynı: iki paket kilitli kurulum + deterministik testler
	cd agent-core && uv sync --frozen --extra dev && uv run --frozen --extra dev pytest -q
	cd lakehouse-core && uv sync --frozen && uv run --frozen pytest -q
