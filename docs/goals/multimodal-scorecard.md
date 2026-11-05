# Multimodal scorecard

Owner 2026-11-05: "start working on the multimodality of cicada. we have to rate it until it is a 10/10", and later the bar:
"being able to play videos, audios, see photos, etc all possible in the app, which all as entities have a markdown
attached to it which can have the summary, why its relevant, if there is a transcription available anywhere (which we
have to put the model that transcribed it as the contributor)."

**Scored 2026-11-05 on `dev` + the Voice Memos PR (G43).** 0 = nothing, 10 = the bar above. A number is given only for what
was checked, with the check named in the evidence column; `n/m` = not measured, and why. Re-score by re-running the checks
(`api/tests/test_media_files.py`, `api/tests/test_image_index.py`, the code the evidence names) and editing the row. Real
values never go in this file. Related: G43, G195 (meaning index 2), G162 (no download), G140 (watch records).

## 1. Getting it in and finding it

| Kind | In | By words | By meaning | Opens at the moment | What the person sees |
|---|---|---|---|---|---|
| YouTube video | 5 | 4 | 4 | n/m | 5 |
| Screen recording | 6 | 0 | 5 | 4 | 6 |
| Any video file | 7 | 0 | 6 | 4 | 6 |
| Image | 5 | 1 | 6 | n/a | 6 |
| Audio file | 7 | 0 | 7 | 4 | 6 |
| Voice Memos | 5 | 0 | 7 | 3 | 5 |

## 2. The owner's bar (2026-11-05)

| Kind | Plays or shows in the app | A page with a markdown body | Summary and why it matters | Transcription shown | Transcriber named |
|---|---|---|---|---|---|
| YouTube video | 6 | 2 | 3 | 0 | 0 |
| Screen recording | 7 | 0 | 0 | 0 | 1 |
| Any video file | 8 | 0 | 0 | 0 | 1 |
| Image | 8 | 1 | 0 | 0 | 0 |
| Audio file | 8 | 0 | 0 | 0 | 1 |
| Voice Memos | 5 | 0 | 0 | 0 | 1 |

"Transcriber named" is 1 where the name is now *recorded* (`meta.json` `transcribed_by`, from the app) and shown nowhere.

## Evidence for each number

- **YouTube video.** *In 5:* a saved link is captured; Cicada never downloads or transcribes (G162), so the words come only
  from the person's own agent through `cicada_record_watch` (a summary and at most 12 timestamped excerpts of 240
  characters, `watch_record.py`). *By words 4:* that watch episode is an ordinary episode, so it is as findable as one, but an
  unwatched video is its title alone; the saves of ruling 62 are indexed, never read. *By meaning 4:* the excerpts embed as an
  episode; YouTube's own still joins the picture kind (`image_index.sources`, only with the image encoder installed). *Opens at
  the moment n/m:* excerpts carry `[m:ss]` but whether the Reader seeks the embed to one was not tested. *Sees 5, plays 6:* a
  saved video draws as a thumbnail that opens the provider's own player in place (`MediaPreview` `embedVideo`, Video rail);
  not run here. *Page 2:* a save with no reason makes no page (ruling 62), so only a watched or reasoned video has one.
  *Summary 3:* the watch record's summary lands in an episode and a claim, not on a page body.
- **Screen recording and any video file.** Both are the same path: the person drops or picks the file
  (`IntakeRouter` → `MediaFileIndexer`); the app transcribes on the Mac and keeps one frame per shot; `POST /files/media`.
  *In 6/7:* `api/tests/test_media_files.py` (29 pass, synthetic); the app side is covered by fixtures only, and nothing
  drives the live recogniser (it raises a prompt); a screen recording with no speech lands as frames alone (hence 6).
  *By words 0:* the `files` text kind is vectors only, in no lexical index (`media_files` has no FTS leg; only
  `search_service` and `mcp_tools` read it). *By meaning 6 (video) / 5 (screen):* the words are the `files` kind: on the
  real text model 3 of 3 said topics shown, 0 of 4 unsaid (`storage.md`, measured 2026-10-28, not re-run today); frames are
  pictures, lift 0.10 to 0.15 on 400 synthetic shapes and not re-checked on real screenshots (`image_index` docstring).
  *Opens 1:* a hit opens the whole file in the default app (`ContentView` `.addedFile`), at 0:00; the time is only in the
  hit's text. *Sees 4:* a find-palette row with the frame, "the recording's words, at 12:34". *Plays 0:* no in-app player for
  an added file (AVKit exists for a media page's `fileVideo`, not for these). *Transcriber 1:* see above.
- **Image.** *In 3:* pictures reach the index only from what Cicada already holds (a look, a site capture, a media preview, a
  YouTube still, a video frame); a loose photo file has no door (`IntakeRouter` handles no image type; `PictureImport` makes a
  page's portrait, 512 px, nothing more). *By words 1:* a page's or look's title and note, no text read out of the picture
  (no OCR found). *By meaning 6:* the pinned image encoder puts a picture in the text model's space; 32/32 first pictures right
  and 0/30 shown for nothing on synthetic shapes (`storage.md`, `image_index_build`), real photos not measured. *Plays/shows 2:*
  a page or preview draws its picture; there is no viewer for an image file. *Page 1:* a look or preview hangs on a page that
  exists for another reason.
- **Audio file.** The video path without frames. *In 7, by meaning 7:* the same tests and the same measured floors; no real
  podcast or meeting was run (n/m). *Opens 1, sees 3, plays 0:* as above, no waveform or time, no player.
- **Voice Memos (this PR).** *In 5:* the reader, tile (Apple's own icon drawn from the installed app), route and store are
  built and `test_media_files.py` passes (29, 14 of them for this source); the Swift tests compile (`swift build --build-tests`) and were run by the coordinator;
  the table and column names are Core Data's usual and were **not checked against a real store** (see below), so a live read
  is unproven. *By words 0, by meaning 7:* identical to an audio file, through the same `files` kind and the same tests
  (`test_media_files.py` adds: one item per recording by id, dated by its own date, an edit re-stages, a deletion is
  tombstoned, a demo bank refuses). *Opens 1, sees 3, plays 0:* the hit opens the recording in the default app
  (`MediaFilePlaces` remembers the file for each memo); no time.

## Re-score after the player (ROR-117, PR 646, coordinator, 2026-11-05)

Checked by running the real app on a scratch home with synthetic files: an H.264 MP4, an AAC M4A and a JPEG. The Swift suites
named in the PR pass (143 run, 0 failed, 1 skipped). Each number below replaces the older evidence for that cell.

- **Plays or shows, video 8, audio 8, image 8.** A search hit played the video in the app, the list opened the audio with its
  position moving, and the photo opened in the viewer. Not 10: only those three formats were run, the photo and a recording were
  posted through the API rather than the picker, and none of it shows yet on the item's own page.
- **Screen recording 7.** The same player, but no real screen recording was run, and one with no speech has no words to reach a moment by.
- **Voice Memos 5.** The same player, but no real memo has ever been read on this Mac, so a real store's file is unproven.
- **Opens at the moment 4 (3 for Voice Memos).** A hit opens at the second its result names, but that second is the start of the
  passage, not of the words. A sentence said at 0:12 opened at 0:00 in the run. Fixing this is on the by-words PR.
- **What the person sees 6 (5 for Voice Memos).** A real surface for each kind, a moved file says so with a way to choose it
  (run on a moved MP4). There is still no transcript or summary beside the player.
- **Image in 5.** A photo has a door by drop or pick and an item in the list. The door is covered by tests only, and a folder of photos has no door.

## What is missing for a 10, per column (the follow-up's list)

- **Plays or shows:** an in-app player for an added audio or video file (AVKit exists only behind `AVPlaybackController`, R-V6;
  the media page's `fileVideo` is the model), seeking to the matched second; an image viewer; the player and viewer inside the
  find palette's hit and the item's own page. YouTube: seek the embed to a cited `[m:ss]`.
- **A page with a markdown body:** an added file or memo is JSON outside every bank, not an entity. A page means a new
  entity type or the `media` type (Stage 1 never produces `media`; repositories are the precedent, ruling 53) plus a writer.
- **Summary and why it matters:** needs a model read of the words; today nothing reads them (below).
- **Transcription shown:** `transcript.json` exists per item; no route serves it and no view shows it. A `GET /files/<id>`
  returning the scrubbed segments is the first step.
- **Transcriber named:** recorded now, one fixed name (`Apple on-device speech`, the Mac's recogniser exposes no model id).
  Shown as a contributor nowhere; the Home contributor strip and a page's History would have to read `meta.json`.
- **By words:** a lexical leg over the passages (the FTS index is derived and disposable, so adding a kind is cheap, but
  "a search embeds words only" and the index would hold the recording's words).
- **Opens at the moment:** pass `at` from the hit to the player; needs the player.
- **Image in:** a door for a photo file or folder (G195's folder walk), OCR is a separate decision.

## Rails the follow-up touches (flag, not decided)

1. **"Never read by Sleep" (`media_files`, G195).** A summary and a "why it matters" are model reads of the recording's
   words. Reading them is an owner decision, and for Voice Memos the speaker is usually the person: the words are stored as
   `words_by: the recording`, never their own. Whether Sleep may read memos, and as whose words (`evidence_kind`), is open.
   Not decided here.
2. **Outside every bank vs a markdown page.** The filesystem-and-git bank is the source of truth; the files store is outside
   it on purpose (never in git, never exported). A page whose body holds a transcript moves the words into git history,
   which the "numbers", "sensitive text" and "forget" rails would then have to cover.
3. **Who may make a page.** Ruling 56 (nothing is suggested or created by Sleep), ruling 62 (a save with no reason makes no
   page) and entity promotion (2+ conversations) all say a page is earned. A page per added file would be a new, explicit
   promotion rule, or the page is made only on the person's act.
4. **"No LLM at capture" and "reading stays on this Mac."** A summary needs an engine call; it would run at Sleep's tail or on
   the person's click, through `providers.resolve_llm_fn` (the sensitive-hold door), never on the capture path.
5. **Provider-neutral copy.** Naming the transcriber is provenance, not copy about who did a job; the copy rail allows a
   name "where it shows the person's own current choice". A contributor line naming a recogniser needs the owner's OK.
6. **Video rail (G162).** An in-app player plays a file already on the Mac or the provider's own player URL; it never
   downloads or derives a stream. Extracting a YouTube video stays out.
