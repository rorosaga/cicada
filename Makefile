PYTHON := api/.venv/bin/python
MEMORY ?= memory
QUESTIONS ?= benchmarks/questions.local.yaml
QUERIES ?= benchmarks/queries.local.txt
OUT ?= benchmark_results
EPISODE_LIMIT ?=
ABLATIONS ?= default promotion_1 promotion_3 decay_aggressive decay_loose

.PHONY: help rebuild-episodes table1 table3 table3-sleep table3-sleep-smoke ablation ablation-smoke all-safe all-full

help:
	@printf '%s\n' \
	  'Targets:' \
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

all-safe: rebuild-episodes table1 table3

all-full: rebuild-episodes table1 table3-sleep ablation
