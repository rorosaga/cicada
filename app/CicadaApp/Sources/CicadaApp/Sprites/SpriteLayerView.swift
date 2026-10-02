import SwiftUI

/// Inert sprite leaf: only frame boundaries tick, with a key frame when still or unseen.
struct SpriteLayerView: View {
    let clip: SpriteClip?
    let sheet: SpriteSheet?
    let pixelScale: CGFloat
    /// The declared canvas keeps a missing sheet from moving the room.
    var canvasSize: CGSize? = nil
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePaused) private var hostPaused
    @Environment(\.spriteSnapshotDate) private var snapshotDate
    @State private var windowVisible = true

    var body: some View {
        let profile = SpritePlaybackProfile.of(reduceMotion: reduceMotion, lowPower: SceneStore.shared.lowPower)
        let paused = snapshotDate != nil || SceneRunPolicy.isPaused(windowVisible: windowVisible, hostPaused: hostPaused)
        Group {
            if let clip, clip.order.count > 1, profile != .still, !paused {
                TimelineView(SpriteFrameSchedule(tracks: [.init(origin: SpriteClock.origin,
                    seconds: clip.seconds.map { $0 * profile.slowdown }, loops: true)])) { context in
                    frame(clip.order[clip.loopStep(at: context.date, profile: profile)])
                }
            } else if let clip {
                frame(clip.order.first ?? 0)
            } else {
                frame(nil)
            }
        }
        .background { if snapshotDate == nil { WindowVisibilityReader { windowVisible = $0 } } }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private func frame(_ index: Int?) -> some View {
        let size = canvasSize ?? sheet?.frameSize ?? .zero
        return Group {
            if let index, let cg = sheet?.frameImage(index) {
                Image(decorative: cg, scale: 1).resizable().interpolation(.none)
            } else { Color.clear }
        }
        .frame(width: size.width * pixelScale, height: size.height * pixelScale)
    }
}
