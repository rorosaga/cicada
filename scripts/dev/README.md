# Live-check helpers (macOS, the orchestrator's tools)

Synthetic `osascript … click at` and plain keystrokes do not reach SwiftUI rows in Cicada's window, so
the live checks after a merge use these three instead. Build each once with `swiftc -O <file> -o <name>`.

- `winall` — lists on-screen windows as `<id> <owner> | <title> | W x H @ X Y`; the app window is the line
  containing `Cicada | Cicada`. Capture it with `screencapture -x -o -l <id> out.png` (2× pixels).
- `axfind "<text>" [press]` — lists accessibility elements whose description, title or value contains the
  text; with `press`, AX-presses the first matching button (rail items, inbox rows, "Show in
  conversation", menus).
- `cgclick <x> <y>` — posts a real mouse click at SCREEN points (the graph canvas is a web view, which
  AX cannot reach); window points are window origin + offset.

They need Accessibility permission for the terminal. Never point them at a real bank for screenshots —
README images come from a freshly generated demo bank only (the privacy rule).
