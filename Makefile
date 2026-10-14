PY ?= python3
export PYTHONPATH := src

.PHONY: install test live scenarios controls report llm all clean

install:            ## editable install with test deps (add [llm] for the Anthropic adapter)
	$(PY) -m pip install -e ".[dev]"

test:               ## unit + integration + CLI end-to-end tests
	$(PY) -m pytest

live:               ## opt-in tests against the real Claude API (needs ANTHROPIC_API_KEY or .env)
	$(PY) -m pytest -m live

scenarios:          ## all scenarios, deterministic LLM stand-in, policy guard on
	$(PY) -m purchase_eval run --out runs/mock-guarded

controls:           ## negative controls: a gullible approver with and without the policy guard (expected to FAIL)
	-$(PY) -m purchase_eval run --approver gullible --out runs/gullible-guarded
	-$(PY) -m purchase_eval run --approver gullible --no-guard --out runs/gullible-unguarded

report: scenarios controls  ## HTML report over all three runs
	$(PY) -m purchase_eval report runs/mock-guarded runs/gullible-guarded runs/gullible-unguarded --out runs/report.html

llm:                ## real Claude approver (needs ANTHROPIC_API_KEY or .env, and the [llm] extra)
	$(PY) -m purchase_eval run --approver anthropic --out runs/anthropic-guarded

all: test report

clean:
	rm -rf runs/*-guarded runs/*-unguarded runs/*-demo runs/report.html .pytest_cache
