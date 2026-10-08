PYTHON := api/.venv/bin/python
MEMORY ?= memory
QUESTIONS ?= benchmarks/questions.local.yaml
QUERIES ?= benchmarks/queries.local.txt
OUT ?= benchmark_results
MCP_CONFIG ?= benchmarks/mcp-eval.local.json
EPISODE_LIMIT ?=
ABLATIONS ?= default promotion_1 promotion_3 decay_aggressive decay_loose

INSTALL_FLAGS ?=

.PHONY: help install cli doctor embedding-model app run-app install-app release-app release release-pr dev login-item no-login-item backfill-structural rebuild-episodes table1 table3 table3-sleep table3-sleep-smoke ablation ablation-smoke eval all-safe all-full

help:
	@printf '%s\n' \
	  'Targets:' \
	  '  make install               # plug-and-play install (install.sh)' \
	  '  make doctor                # health checks (scripts/doctor.sh)' \
	  '  make embedding-model       # fetch the on-device search model the release app ships (~130 MB, once)' \
	  '  make install-app           # release-build, install ~/Applications/Cicada.app' \
	  '  make dev                   # rebuild (debug) + reinstall + relaunch the app — the devloop command' \
	  '  make release-app           # build the installable app with its backend (G182; nothing installed)' \
	  '  make release VERSION=x.y.z # owner only: PR the version bump to dev (G182)' \
	  '  make release-pr            # owner only: PR dev → main; merging it is the release (CI tags + publishes)' \
	  '  make login-item            # add Cicada to macOS Login Items (opt-in)' \
	  '  make no-login-item         # remove Cicada from macOS Login Items' \
	  '  make backfill-structural MEMORY=/path/to/memory  # structural entity backfill' \
	  '  make rebuild-episodes      # rebuild episode LEANN index in live memory' \
	  '  make table1                # run Table 1 using QUESTIONS=$(QUESTIONS)' \
	  '  make table3                # static metrics + recall latency using QUERIES=$(QUERIES)' \
	  '  make table3-sleep          # full Table 3 including fresh sleep-cycle timing' \
	  '  make table3-sleep-smoke    # 5-episode smoke test for sleep timing' \
	  '  make ablation              # full Table 2 threshold sweep' \
	  '  make ablation-smoke        # cheap Table 2 smoke test on 5 episodes' \
	  '  make eval                  # retrieval eval using QUESTIONS + MCP_CONFIG' \
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

# G180 — link ~/.local/bin/cicada to this checkout's `scripts/cicada` (no admin; never replaces a working link).
cli:
	@scripts/install-cli.sh

doctor:
	bash scripts/doctor.sh

# The release app's own search model (pinned + sha256-checked in scripts/release/inputs.env) into
# $${CICADA_HOME:-~/.cicada}/models: a checkout then embeds as a release does — onnxruntime, no torch.
embedding-model:
	bash scripts/fetch-embedding-model.sh

# Build the macOS app as a proper .app bundle (NOT `swift run`, which produces
# a bundle-less executable whose window never becomes key — that breaks graph
# node clicks and text-field focus). `make run-app` also launches it.
app:
	cd app/CicadaApp && ./bundle.sh

run-app:
	cd app/CicadaApp && ./bundle.sh --run

# Install a release build as a real ~/Applications/Cicada.app — ad-hoc
# code-signed, deterministic replace-while-running (quits any live instance
# first; aborts rather than half-copying). Run this occasionally; `make dev`
# below is the everyday loop.
install-app:
	cd app/CicadaApp && ./install_app.sh --release

# G182 — the installable app (its own Python, code, git and model), built into
# app/CicadaApp/.build/release/Cicada.app and smoke-tested in a temp folder.
# Installs nothing and never opens the app.
release-app:
	cd app/CicadaApp && ./bundle.sh --release --with-backend
	scripts/release/smoke-test.sh app/CicadaApp/.build/release/Cicada.app

# G182 / TODO ruling 19 — a release is a dev → main PR, and merging it is the
# release: CI tags vX.Y.Z at the merge and publishes the GitHub Release.
# `make release VERSION=x.y.z` opens the version-bump PR to dev; once it is
# merged, `make release-pr` opens the dev → main PR. Neither pushes main or
# tags. The owner runs these; see docs/RELEASING.md.
release:
	@if [ -z "$(VERSION)" ]; then echo "usage: make release VERSION=x.y.z"; exit 2; fi
	scripts/release/release.sh bump $(VERSION)

release-pr:
	scripts/release/release.sh pr

# The everyday devloop command (G88): rebuild debug (fast), reinstall over
# ~/Applications/Cicada.app, relaunch. This replaces `swift build &&
# .build/debug/CicadaApp` — that path produces a bundle-less executable whose
# window never becomes key (see bundle.sh's header), so it's strictly worse
# than this even before counting the two-terminal backend juggling it also
# implies. The backend itself does not need restarting here — it runs
# separately under launchd (`com.cicada.backend`) and `make dev` never
# touches it.
dev:
	cd app/CicadaApp && ./install_app.sh --debug --relaunch

# Opt-in: add/remove Cicada from macOS's own Login Items list (System
# Events) — see login_item.sh for why this isn't a hand-rolled LaunchAgent.
login-item:
	cd app/CicadaApp && ./login_item.sh add

no-login-item:
	cd app/CicadaApp && ./login_item.sh remove

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
