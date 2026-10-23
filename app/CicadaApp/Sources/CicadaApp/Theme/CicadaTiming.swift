import Foundation

/// Delays that are not motion (design §1.1): how long the pointer must rest
/// before something opens, and how long a surface waits before closing so the
/// pointer can travel into it. Reduce Motion leaves these alone — a delay is
/// not an animation — which is exactly why they do not live in
/// `CicadaMotion`, whose every member turns into `nil` under it.
enum CicadaTiming {
    /// G118 slice 2 — the dwell before an evidence chip's quote preview opens.
    /// Long enough that sweeping the pointer across a row of chips opens
    /// nothing; short enough that resting on one feels immediate.
    static let hoverPreviewDelay: TimeInterval = 0.35
    /// The grace before a preview closes after the pointer leaves the chip,
    /// so it can cross the gap into the popover (and its "Open conversation").
    static let hoverPreviewGrace: TimeInterval = 0.2
    /// DR-42 — how long an answer waits for Undo before it is sent. A delay, not motion: Reduce
    /// Motion never shortens the time a person has to take a tap back.
    static let undoWindow: TimeInterval = 5
    /// G198 review B3 — "Who wrote it" asks again this long after the backend said its blame is still running, at
    /// most `blamePendingTries` times in all. A wait, not motion.
    static let blamePendingRetry: TimeInterval = 1.5
    static let blamePendingTries = 4
    /// R-DI3 — how long quit waits for a held answer to land before the app closes anyway.
    static let quitFlushLimit: TimeInterval = 3
    /// Round-4 D5 — how long a Copy button reads "Copied" before it reads Copy again (`CommandBox`'s 1.5 s). A
    /// confirmation's dwell, not motion, so Reduce Motion leaves it alone.
    static let copiedConfirmation: TimeInterval = 1.5
    /// G212 — how often the Sleep page asks `GET /devices/status` while it shows (a machine is "connected" within ten
    /// minutes of its last request, so a half-minute poll is plenty). A wait, not motion.
    static let machinePoll: TimeInterval = 30
    /// How long a toast (`Store.toast`) stays before it clears itself.
    static let toastDwell: TimeInterval = 4
    /// G218 — how often `PermissionDragHelper` asks, by preflight only, whether the person has allowed the permission
    /// yet. Gentle: a preflight is a cheap local read, and a second is quick enough that the panels close as the switch
    /// flips. A wait, not motion.
    static let permissionPoll: TimeInterval = 1
    /// G218 — how long screenshots stay shown after Touch ID before they are dropped from memory and hidden again.
    static let traceScreenshotsShown: TimeInterval = 300
}
