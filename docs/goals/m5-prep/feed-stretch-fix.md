# Feed page forces + locks the window HEIGHT — real root cause & minimal fix

## Symptom
Selecting the **Feed** tab forces the window to full **screen height** and locks
vertical resize. Graph / Inbox / Clusters / Sleep all resize normally. Two prior
reports; one prior fix attempt did NOT resolve it.

## What was already tried (and did NOT fix it)
- `c543ee9` removed the page-background `.ignoresSafeArea()` from Feed/Topics/Sleep.
- A later pass added `.frame(maxWidth: .infinity, maxHeight: .infinity)` to Feed's
  **root ZStack** (`FeedView.swift:53`) with the comment "Claim the full detail
  column so `.prominentDetail` doesn't let the content's intrinsic (narrow) width
  drive the window into a tall shape."

That added frame is itself the remaining cause — see below.

## Root cause (file:line)

`app/CicadaApp/Sources/CicadaApp/Views/Feed/FeedView.swift:53`

```swift
.frame(maxWidth: .infinity, maxHeight: .infinity)   // on the root ZStack
```

### Why this, specifically, forces + locks height

1. Feed's root is a **`ZStack`** whose first child is a **bare
   `CicadaTheme.background` Color** (`FeedView.swift:17`). A SwiftUI `Color`/shape
   has **no intrinsic size and reports an unbounded ideal** — it accepts any
   proposal, including infinity. A `ZStack` adopts the **union (max)** of its
   children's ideal sizes, so the ZStack's ideal height becomes **unbounded**.

2. Wrapping that already-unbounded-ideal ZStack in
   `.frame(maxHeight: .infinity)` keeps the **infinite ideal height propagating
   upward** instead of clamping it.

3. `ContentView` hosts the page as the **detail** column of a
   `NavigationSplitView` styled `.prominentDetail`
   (`ContentView.swift:11-22`, already wrapping `detailContent` in its own
   `.frame(maxWidth:.infinity, maxHeight:.infinity)` at line 19). Under
   `.prominentDetail` the split view sizes the detail to the **content's ideal /
   prominent size**. Feed hands it an **infinite ideal height** → the window is
   driven to full screen height and the vertical dimension is **locked**.

### Why the other pages do NOT have the bug (the proof)

- **Sleep** (`SleepView.swift`) and **Topics/Clusters** (`TopicsView.swift`)
  use the *same* `ZStack { CicadaTheme.background; … }` shape but **do NOT put any
  `.frame(maxHeight: .infinity)` on the root ZStack** (TopicsView's ZStack has no
  trailing `.frame` at all; SleepView's likewise). The greedy `Color` child still
  makes them fill the width/height the split view *proposes*, but no infinite
  ideal escapes upward, so `.prominentDetail` proposes a normal, resizable height.
- **Inbox** (`InboxListView.swift:49`) *does* carry
  `.frame(maxWidth:.infinity, maxHeight:.infinity)` but its root is a **`VStack`**
  whose background is a `.background(CicadaTheme.background)` **modifier**
  (`InboxListView.swift:54`) — a background modifier **never contributes layout
  size**. The VStack's ideal height is the **finite sum** of its real children, so
  `.frame(maxHeight:.infinity)` makes it greedy-but-**bounded**; no infinite ideal,
  no lock.

So the bug is the **combination unique to Feed**: a root **ZStack with a bare
`Color` layout child** (unbounded ideal) **plus** an explicit
`.frame(maxHeight: .infinity)` on that ZStack, sitting in a `.prominentDetail`
detail column. The G11 `FeedRow` `.sheet`/`FeedItemPreviewSheet`/`MediaPreview`/
`WebView` additions are **layout-inert to the base window**: the `WebView`
(`WebView.swift`) only ever appears inside `.sheet`-presented `WebPreviewSheet`
(fixed `900x620`) and `FeedItemPreviewSheet` (fixed `480x520`), never in the base
layout, so a WKWebView intrinsic size is NOT the cause here.

## Minimal fix

Match the proven Sleep/Topics pattern: keep the greedy `CicadaTheme.background`
`Color` (which already claims full width and height the split view proposes) and
**drop the explicit infinity frame from the root ZStack** so no infinite ideal
height leaks into `.prominentDetail`.

`FeedView.swift:51-53` — remove:

```swift
// Claim the full detail column so `.prominentDetail` doesn't let the
// content's intrinsic (narrow) width drive the window into a tall shape.
.frame(maxWidth: .infinity, maxHeight: .infinity)
```

Width does not collapse without it: the `CicadaTheme.background` `Color` child is
horizontally greedy (exactly as in Sleep/Topics), and `ContentView` already wraps
`detailContent` in `.frame(maxWidth:.infinity, maxHeight:.infinity)`.

### Preserved behavior (unchanged)
Media preview (G11 sheet), search, segmented sort, upload overlay, and the
bookworm empty state are untouched — the fix only removes a sizing modifier on the
outermost container.

## Verification
`cd app/CicadaApp && swift build` → exit 0. Visual resize behavior confirmed by
the human against the running app.
