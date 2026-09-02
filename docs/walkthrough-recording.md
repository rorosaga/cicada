# Recording the import walkthrough clips (G64)

The `+` sheet on the Capture page reserves a 16:9 area per vendor. It plays
`app/CicadaApp/Sources/CicadaApp/Resources/walkthroughs/<vendor>.mp4` when that
file exists (muted, looping, no controls) and shows a "coming soon" placeholder
otherwise. Nothing else needs to change to ship a clip — `Package.swift` uses
`.copy("Resources")`, so dropping the file in is enough.

## Vendors and file names

| Vendor | File | Export page the clip must land on |
|---|---|---|
| Claude | `claude.mp4` | https://claude.ai/settings/data-privacy-controls |
| ChatGPT | `chatgpt.mp4` | https://chatgpt.com/#settings/DataControls |
| Google Takeout | `takeout.mp4` | https://takeout.google.com/ |
| Instagram | `instagram.mp4` | https://accountscenter.instagram.com/info_and_permissions/dyi/ |

The vendor list and these URLs are pinned by
`app/CicadaApp/Tests/CicadaAppTests/WalkthroughTests.swift`; change them there
first if a vendor moves its page.

## Constraints

- **1280×720, 16:9**, H.264 MP4.
- **≤ 2 MB per clip.** They ship inside the app bundle.
- **No audio** — the player is muted and looping, so a soundtrack is dead weight.
- **10–20 s.** Long enough to show the click path, short enough to loop cleanly.
- **Never record real personal data.** Use a throwaway account, or blur the
  conversation list. The clip ships to every user.

## How to record

Either works:

1. **Screen Studio** — records at 2× with automatic cursor zoom, exports MP4
   directly. Set the canvas to 1280×720 and turn the background padding off.
2. **`screencapture -v`** (built in):
   ```sh
   screencapture -v -R 0,0,1280,720 ~/Desktop/claude-raw.mov
   # ...perform the click path, then Ctrl-C
   ffmpeg -i ~/Desktop/claude-raw.mov -vf scale=1280:720 -an \
       -c:v libx264 -crf 30 -preset slow -movflags +faststart \
       app/CicadaApp/Sources/CicadaApp/Resources/walkthroughs/claude.mp4
   ```
   `screencapture` has no cursor zoom, so keep the click targets large — resize
   the browser window rather than relying on post-hoc magnification.

Check the size with `ls -lh` before committing; re-encode at a higher `-crf` if
a clip is over 2 MB.
