.PHONY: test build demo-check

test:
	uv run pytest -q

build:
	mkdir -p data/raw data/bronze data/silver data/quarantine
	@echo "Phase 0.5 base directories are ready; no Silver/Gold build is performed."

demo-check:
	uv run pytest -q tests/contract/test_shared_base.py
