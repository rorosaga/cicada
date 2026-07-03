PYTHON := api/.venv/bin/python
MEMORY ?= memory
QUESTIONS ?= benchmarks/questions.local.yaml
QUERIES ?= benchmarks/queries.local.txt
OUT ?= benchmark_results
MCP_CONFIG ?= benchmarks/mcp-eval.local.json
EPISODE_LIMIT ?=
ABLATIONS ?= default promotion_1 promotion_3 decay_aggressive decay_loose

INSTALL_FLAGS ?=

.PHONY: help install doctor app run-app backfill-structural rebuild-episodes table1 table3 table3-sleep table3-sleep-smoke ablation ablation-smoke eval all-safe all-full

help:
	@printf '%s\n' \
	  'Targets:' \
	  '  make install               # plug-and-play install (install.sh)' \
	  '  make doctor                # health checks (scripts/doctor.sh)' \
	  '  make backfill-structural MEMORY=/path/to/memory  # structural entity backfill' \
	  '  make rebuild-episodes      # rebuild episode LEANN index in live memory' \
	  '  make table1                # run Table 1 using QUESTIONS=$(QUESTIONS)' \
	  '  make table3                # static metrics + recall latency using QUERIES=$(QUERIES)' \
	  '  make table3-sleep          # full Table 3 including fresh sleep-cycle timing' \
	  '  make table3-sleep-smoke    # 5-episode smoke test for sleep timing' \
	  '  make ablation              # full Table 2 threshold sweep' \
	  '  make ablation-smoke        # cheap Table 2 smoke test on 5 episodes' \
	  '  make all-safe              # rebuild episodes + table1 + table3 (no sleep-cycle spend)' \
	  '  make all-full              # rebuild episodes + table1 + table3-sleep + ablation' \
	  '' \
	  'Variables:' \
	  '  QUESTIONS=benchmarks/questions.local.yaml' \
	  '  QUERIES=benchmarks/queries.local.txt' \
	  '  MEMORY=memory' \
	  '  OUT=benchmark_results' \
	  '  EPISODE_LIMIT=5'

install:
	bash install.sh $(INSTALL_FLAGS)

doctor:
	bash scripts/doctor.sh

# Build the macOS app as a proper .app bundle (NOT `swift run`, which produces
# a bundle-less executable whose window never becomes key — that breaks graph
# node clicks and text-field focus). `make run-app` also launches it.
app:
	cd app/CicadaApp && ./bundle.sh

run-app:
	cd app/CicadaApp && ./bundle.sh --run

# Structural (free, no-LLM) entity-page backfill. MEMORY must be passed
# explicitly on the command line; we refuse the bare default to avoid silently
# rewriting the live memory dir. e.g. make backfill-structural MEMORY=/tmp/m
backfill-structural:
	@if [ "$(origin MEMORY)" != "command line" ]; then \
		echo "MEMORY must be passed explicitly: make backfill-structural MEMORY=/path/to/memory"; \
		exit 2; \
	fi
	$(PYTHON) -m scripts.backfill_entity_pages --memory $(MEMORY) --structural

rebuild-episodes:
	$(PYTHON) -m benchmarks.rebuild_leann --only episodes --memory $(MEMORY)

table1:
	$(PYTHON) -m benchmarks.run_table1 \
		--questions $(QUESTIONS) \
		--memory $(MEMORY) \
		--out $(OUT)/table1

table3:
	$(PYTHON) -m benchmarks.run_table3 \
		--memory $(MEMORY) \
		--queries $(QUERIES) \
		--out $(OUT)/table3

table3-sleep:
	$(PYTHON) -m benchmarks.run_table3 \
		--memory $(MEMORY) \
		--queries $(QUERIES) \
		--sleep-cycle-time \
		$(if $(EPISODE_LIMIT),--episode-limit $(EPISODE_LIMIT),) \
		--out $(OUT)/table3

table3-sleep-smoke:
	$(MAKE) table3-sleep EPISODE_LIMIT=5

ablation:
	$(PYTHON) -m benchmarks.run_ablation \
		--memory $(MEMORY) \
		$(if $(EPISODE_LIMIT),--episode-limit $(EPISODE_LIMIT),) \
		--out $(OUT)/table2

ablation-smoke:
	$(MAKE) ablation EPISODE_LIMIT=5

eval:
	$(PYTHON) -m benchmarks.run_retrieval_eval \
		--questions $(QUESTIONS) \
		--mcp-config $(MCP_CONFIG) \
		--out $(OUT)/retrieval_eval

all-safe: rebuild-episodes table1 table3

all-full: rebuild-episodes table1 table3-sleep ablation
