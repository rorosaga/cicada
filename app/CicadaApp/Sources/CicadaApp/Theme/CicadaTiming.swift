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
}
