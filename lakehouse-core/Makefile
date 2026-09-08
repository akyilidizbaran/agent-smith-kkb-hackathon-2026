.PHONY: test build demo-check

PYTHON ?= python3

test:
	$(PYTHON) -m pytest -q

build:
	mkdir -p data/raw data/bronze data/silver data/quarantine
	@echo "Phase 0.5 base directories are ready; no Silver/Gold build is performed."

demo-check:
	$(PYTHON) -m pytest -q tests/contract/test_shared_base.py
