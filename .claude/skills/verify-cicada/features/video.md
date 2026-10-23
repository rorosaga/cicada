# Video queue and watching

Saved videos form a queue an agent works through; after watching, it records a summary with short timestamped quotes, never the transcript.

## Sub-features

- `video-queue`, `video-claim`, `video-release`, `record-watch`, `record-youtube-list`, `videos-state`.

## How to get to it (user POV)

- Sleep's Saved tab; Sources.
- MCP `cicada_video_queue`, `cicada_video_claim`, `cicada_record_watch`, `cicada_record_youtube_list`.
- `GET /videos/state`, `/videos/summary`, `PUT/DELETE /videos/queue/{key}`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- A link saved with `cicada_save_url` (saved-links-and-reading).

- **Queue.** Run `$CV mcp call cicada_video_queue '{}'` and `$CV mcp call cicada_video_claim '{}'`. On a run with no provider video: `Nothing is waiting in the person's video queue.`
- **Watch.** Run `$CV mcp call cicada_record_watch '{"url": "https://example.com/paper", "summary": "verify", "excerpts": [{"t": 12, "quote": "verify quote"}], "basis": "transcript"}'` on the saved link. `Recorded the watch …`, an episode and a `describes` claim.
- **State.** Run `$CV api GET /videos/state`. Lists provider videos only, so it stays empty here.

**Not driven in a verify run: the queue's lease lifecycle.** A video enters the queue only as a provider's video link
(YouTube and friends), and saving one fetches that provider's page, which the run keeps to `example.com`. The nearest
checks: the steps above, and the `verify-video-queue` skill, which model-checks claim, lease, refresh, release and the
watch credit in TLA+. A release carries the lease: `{"release": [{"url": …, "lease_token": …, "code": …, "reason": "verify"}]}`.

## Gotchas

- `cicada_record_youtube_list` reads the person's signed-in YouTube pages through their own agent; never drive it in a verify run.
- `cicada_record_watch` on a link that is not saved yet saves it first, and that save fetches the page. Record watches only on links the journey already saved.
