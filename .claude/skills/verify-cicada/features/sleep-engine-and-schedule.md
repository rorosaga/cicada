# Sleep engine and schedule

The person chooses what Sleep reads with (Auto, Claude plan, ChatGPT plan, a key, a local model) and when it runs on its own, and is told in words what a manual and a scheduled run would use.

## Sub-features

- `engine-view` shows each engine's readiness and what a run would use.
- `engine-choose` sets the engine and its model.
- `schedule` sets when Sleep runs on its own and whether scheduled runs may use the plan.
- `run-options` sets per-run options such as batch size.

## How to get to it (user POV)

- Settings → Engines and Settings → Sleep; the Sleep page's engine menu.
- `GET/PUT /sleep/engine`, `GET/PUT /sleep/schedule`, `GET/PUT /sleep/run-options`.
- `cicada engine list`, `cicada sleep engine`, `cicada sleep schedule`, `cicada sleep options`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).

- **Readiness.** Run `$CV api GET /sleep/engine --save api/engine.json`. `mode` is `agent`, `model` is `haiku`, `preview.manual.billing` and `preview.scheduled.billing` are `plan`.
- **CLI.** Run `$CV cli -- engine list`. The Claude plan reads `signed in`.
- **Schedule.** Run `$CV api GET /sleep/schedule`. The answer carries the schedule and, while a schedule is on with no usable engine, a `warning`.
- **App.** Open Settings (`vclick 'Description: Settings,'`), then the Engines row; `$CV app shot engines`.

## Gotchas

- The run pins `CICADA_LLM_MODE=agent` in the environment, so the app's engine chooser cannot move it; a PUT that changes the engine is answered but the environment wins. Do not choose a metered key or the ChatGPT plan in a verify run.
- Answers name the plan's account email. Keep that evidence local.
