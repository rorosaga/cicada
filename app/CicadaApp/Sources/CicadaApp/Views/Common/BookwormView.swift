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
///
/// `pose` and `reaction` are response art (Track Z R-Z1). They are
/// `.idle`/`nil` everywhere except the Sleep room, so the menu bar, empty
/// states, onboarding and the upload overlay are unchanged.
struct BookwormView: View {
    let state: BookwormState
    /// Multiples of 24 keep cells integer (R3): 48 (inline), 96 (empty states), 120 (Sleep).
    var pointSize: CGFloat = 96
    var caption: String? = nil
    var captionFont: Font = CicadaTheme.font(size: 13, weight: .semibold)
    var captionColor: Color = CicadaTheme.textTertiary
    var alignment: HorizontalAlignment = .center
    /// Track Z §6.1 — where the worm looks / how it answers a drag. Folded
    /// through `BookwormPose.effective(for:reduceMotion:)` so a state §6.4
    /// suppresses (sleeping, error) never shows it.
    var pose: BookwormPose = .idle
    /// A beat in flight (≤ 3 frames, R-Z12); `nil` plays the pose loop.
    var reaction: ActiveReaction? = nil

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

    /// Which beat frame to show — `nil` once the beat has played (the view
    /// falls back to its loop, and `WormStage` clears the reaction). Before
    /// the start it holds frame 0 rather than trapping.
    nonisolated static func reactionFrameIndex(at date: Date, startedAt: Date, count: Int) -> Int? {
        guard count > 0 else { return nil }
        let elapsed = date.timeIntervalSince(startedAt)
        guard elapsed >= 0 else { return 0 }
        let index = Int((elapsed / BookwormSprites.reactionInterval).rounded(.down))
        return index < count ? index : nil
    }

    var body: some View {
        // Track Z §6.1: the pose as this state and Reduce Motion allow it.
        let effective = pose.effective(for: state, reduceMotion: reduceMotion)
        let look = BookwormLook.pose(effective)
        let (frames, interval) = BookwormSprites.frames(for: state, look: look)
        // A beat plays only with Reduce Motion off and only where §6.4 allows
        // it; `BookwormLook.beat` folds the gaze so its key is a counted one.
        let beat: BookwormLook? = reduceMotion ? nil
            : reaction.flatMap { BookwormLook.beat($0.kind, for: state, gaze: effective.gaze) }
        // G130 R6: scale the mascot with the rest of the chrome, but snap
        // back onto a multiple of 24 so a cell never lands on a fractional
        // point and the renderer's cache key — an `Int` — stays stable.
        let scaledSize = BookwormRenderer.snappedPointSize(pointSize * CicadaTheme.uiScale)
        VStack(alignment: alignment, spacing: CicadaTheme.spacingSM) {
            if let r = reaction, let beat {
                let count = BookwormSprites.frames(for: state, look: beat).frames.count
                TimelineView(.periodic(from: r.startedAt, by: BookwormSprites.reactionInterval)) { context in
                    // Held on the last frame once the beat has played (§6.1);
                    // `WormStage` clears the reaction right after.
                    let idx = Self.reactionFrameIndex(at: context.date, startedAt: r.startedAt, count: count)
                        ?? max(0, count - 1)
                    sprite(beat, frameIndex: idx, size: scaledSize)
                }
            } else {
                TimelineView(.periodic(from: Self.timelineOrigin, by: interval)) { context in
                    let idx = Self.frameIndex(at: context.date, interval: interval, count: frames.count,
                                              reduceMotion: reduceMotion)
                    sprite(look, frameIndex: idx, size: scaledSize)
                }
            }
            if let caption {
                Text(caption)
                    .font(captionFont)
                    .foregroundStyle(captionColor)
            }
        }
    }

    /// One frame through the one mascot cache. The fixed frame means a tick
    /// never causes layout.
    private func sprite(_ look: BookwormLook, frameIndex: Int, size: CGFloat) -> some View {
        Image(nsImage: BookwormRenderer.cachedImage(state: state, look: look, frameIndex: frameIndex, pointSize: size))
            .interpolation(.none)
            .frame(width: size, height: size)
            .accessibilityLabel("\(state.title) — \(state.detail)")
    }
}
