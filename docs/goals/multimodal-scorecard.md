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
| Screen recording | 6 | 6 | 5 | 8 | 7 |
| Any video file | 7 | 9 | 6 | 8 | 7 |
| Image | 5 | 6 | 6 | n/a | 6 |
| Audio file | 7 | 9 | 7 | 8 | 7 |
| Voice Memos | 5 | 7 | 7 | 6 | 6 |

## 2. The owner's bar (2026-11-05)

| Kind | Plays or shows in the app | A page with a markdown body | Summary and why it matters | Transcription shown | Transcriber named |
|---|---|---|---|---|---|
| YouTube video | 6 | 2 | 3 | 0 | 0 |
| Screen recording | 8 | 9 | 7 | 7 | 8 |
| Any video file | 9 | 9 | 8 | 8 | 8 |
| Image | 9 | 8 | 2 | n/a | n/a |
| Audio file | 9 | 9 | 8 | 8 | 8 |
| Voice Memos | 6 | 8 | 7 | 7 | 8 |

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

## Re-score after search by words (ROR-117, PR 647, coordinator, 2026-11-05)

Checked in the real app on a scratch home: typing six letters of a word said once at 0:12 in a synthetic MP4 found it as
you type, with no model on the machine, and the hit opened the player at 0:12. Backend tests pass (`test_file_words.py`), Swift
suites named in the PR pass (139 run, 0 failed, 1 skipped), including the Mac's recogniser reading words off a drawn picture.

- **By words, video 9, audio 9.** Recall of a word said once was 90 of 90 at rank 1 in 1,800 synthetic passages. Palette cost is
  p95 +1.1 ms at 25,000 passages on a loaded Mac. Not 10: no real recording with accents, crosstalk or mistranscribed names was run.
- **Screen recording 6, image 6.** The text read from kept frames and photos is searchable, but no real screen recording or real
  photo has been run. Frames are kept per shot, so text on screen between shots is not read.
- **Voice Memos 7.** The same path, and no real memo has ever been read.
- **Opens at the moment 8 (6 for Voice Memos).** A word hit lands on the second of the segment that says it, as the run shows. A
  meaning hit lands on the segment holding the most query words, and on a paraphrase holding none of them, on the passage's start. A
  segment can run several seconds, so the second is the segment's start, not the word's.
- **What the person sees 7 (6 for Voice Memos, 6 for an image).** A row now shows the words and their real time.

## Re-score after item pages (ROR-117, PR 648, coordinator, 2026-11-05)

Checked in the real app on a scratch home with synthetic files. This run found two faults the tests had passed: the page dropped
its player data, and the transcript was never fetched. Both are fixed; the numbers below are after the fixes.

- **A page 8 (7 for Voice Memos).** Each added item has one page, with no transcript word in the page file or in git history.
  Not 9: the Summary and Why it matters sections are still empty, and the page opens in the graph's side panel from a row that
  says only "Media".
- **Plays or shows 9, screen recording 8, Voice Memos 6.** The file now plays on its own page, and a timestamp seeks it (clicked
  0:12 on a synthetic MP4). Not 10: only three formats have been run, and no real screen recording or real memo.
- **Transcription shown 8 (7 for screen recording and Voice Memos).** Every segment with a stamp that seeks. Not 10: a long
  recording's transcript has not been run for speed, and there is no search within it. A screen recording with no speech has no transcript.
- **Transcriber named 8.** "Transcribed by" sits above the words, and the name is in the provenance reply. Not 10: the Mac's
  recogniser gives one fixed name, with no version.
- **Summary and why it matters 0.** Next PR.
- **YouTube is unchanged:** none of these three PRs touched it.

## Re-score after the summaries (ROR-117, PR 650, coordinator, 2026-11-05)

Checked in the real app on a scratch home, the plan at haiku: "Read it now" on a synthetic recording wrote its summary as one commit
by the model, and the page drew it. The worker's run through Sleep gave a recording tied to a known project a why-it-matters naming
it, and left an unrelated one empty. The review then tightened two checks: a name must match as whole words, and a note
may not repeat the recording.

- **Summary and why it matters, video and audio 8, screen recording and Voice Memos 7.** Read once per version of the words, by
  Sleep or a click. Not 10: no recording over about a minute has been read, no real recording at all, so how good a summary is on
  real speech is not measured, and a recording past 30,000 characters is read from its start only (the page says so).
- **Image 2.** A photo with text read from it can be summarised from those words alone. Nothing describes a picture itself: that
  needs an engine that takes images, not decided.
- **A page 9 (8 for image and Voice Memos).** Its body now holds what it should, apart from the image case above. Not 10: the
  page opens from a row that says only "Media", in the graph's side panel.

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
