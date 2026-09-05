import SwiftUI

/// The in-app bookworm (G107): the same 24×24 colour frames the menu bar
/// shows, at page size, always moving. Frame selection is a pure function of
/// the clock (`frameIndex(at:…)`) driven by a `TimelineView`, so there is no
/// `Timer` to leak, no `@State` to reset on a state change, and two worms on
/// one screen tick in step. Reduce Motion holds frame 0 (ruling R7).
///
/// Colour art is never tinted and never template-rendered (ruling R4): the
/// palette IS the mood, and a template image would flatten it to a
/// silhouette. Every frame comes from `BookwormRenderer.cachedImage` (R5) —
/// a tick is a dictionary hit, never a rasterization.
///
/// `caption` is the optional bracket line under the worm — the Sleep page's
/// `[ 47 episodes behind ]` text survives there as a caption rather than as
/// the mascot (the 2026-09-02 ask that superseded G107's interim ruling).
struct BookwormView: View {
    let state: BookwormState
    /// Multiples of 24 keep cells integer (R3): 48 (inline), 96 (empty states), 120 (Sleep).
    var pointSize: CGFloat = 96
    var caption: String? = nil
    var captionFont: Font = CicadaTheme.font(size: 13, weight: .semibold, design: .monospaced)
    var captionColor: Color = CicadaTheme.textTertiary
    var alignment: HorizontalAlignment = .center

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// A fixed origin so the schedule's phase never depends on when a
    /// particular view appeared — and so the date a `TimelineView` tick
    /// hands `frameIndex(at:)` names the same frame the schedule fired for.
    static let timelineOrigin = Date(timeIntervalSinceReferenceDate: 0)

    /// Which frame to show at `date`. Pure; tested. Negative or degenerate
    /// inputs clamp to frame 0 rather than trapping — a `count` of 0 or an
    /// `interval` of 0 would otherwise divide by zero, and a date before the
    /// reference epoch yields a negative tick that must still wrap into range.
    nonisolated static func frameIndex(at date: Date, interval: TimeInterval, count: Int, reduceMotion: Bool) -> Int {
        guard count > 0, interval > 0, !reduceMotion else { return 0 }
        let ticks = Int((date.timeIntervalSinceReferenceDate / interval).rounded(.down))
        return ((ticks % count) + count) % count
    }

    var body: some View {
        let (frames, interval) = BookwormSprites.frames(for: state)
        // G130 R6: scale the mascot with the rest of the chrome, but snap
        // back onto a multiple of 24 so a cell never lands on a fractional
        // point and the renderer's cache key — an `Int` — stays stable.
        let scaledSize = BookwormRenderer.snappedPointSize(pointSize * CicadaTheme.uiScale)
        VStack(alignment: alignment, spacing: CicadaTheme.spacingSM) {
            TimelineView(.periodic(from: Self.timelineOrigin, by: interval)) { context in
                let idx = Self.frameIndex(at: context.date, interval: interval, count: frames.count, reduceMotion: reduceMotion)
                Image(nsImage: BookwormRenderer.cachedImage(state: state, frameIndex: idx, pointSize: scaledSize))
                    .interpolation(.none)
                    .frame(width: scaledSize, height: scaledSize)
                    .accessibilityLabel("\(state.title) — \(state.detail)")
            }
            if let caption {
                Text(caption)
                    .font(captionFont)
                    .foregroundStyle(captionColor)
            }
        }
    }
}
