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
- A saved video link (save one with `cicada_save_url`; that save fetches the page's title from this Mac, see saved-links-and-reading).

- **Queue.** Run `$CV mcp call cicada_video_queue '{}'`. The saved video.
- **Claim.** Run `$CV mcp call cicada_video_claim '{}'` until empty; release one with `{"release": [{"url": ..., "code": ..., "reason": "verify"}]}`.
- **Watch.** Run `$CV mcp call cicada_record_watch '{"url": ..., "summary": "verify", "excerpts": [{"t": 12, "quote": "..."}], "basis": "transcript"}'`. `$CV api GET /videos/state` shows it watched.

## Gotchas

- `cicada_record_youtube_list` reads the person's signed-in YouTube pages through their own agent; never drive it in a verify run.
- `cicada_record_watch` on a link that is not saved yet saves it first, and that save fetches the page. Record watches only on links the journey already saved.
