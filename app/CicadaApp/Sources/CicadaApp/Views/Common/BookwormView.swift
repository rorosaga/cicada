import SwiftUI

/// The in-app mascot on the shared sprite clock. State and response precedence remain the matrix's.
struct BookwormView: View {
    let state: BookwormState
    var pointSize: CGFloat = 96
    var latticeCell: CGFloat? = nil
    var caption: String? = nil
    var captionFont: Font = CicadaTheme.font(size: 13, weight: .semibold)
    var captionColor: Color = CicadaTheme.textTertiary
    var alignment: HorizontalAlignment = .center
    var pose: BookwormPose = .idle
    var reaction: ActiveReaction? = nil
    var transition: ActiveTransition? = nil

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePaused) private var hostPaused
    @State private var windowVisible = true

    var body: some View {
        let size = BookwormSize.resolve(pointSize: pointSize, uiScale: CicadaTheme.uiScale, latticeCell: latticeCell)
        let profile = SpritePlaybackProfile.of(reduceMotion: reduceMotion, lowPower: SceneStore.shared.lowPower)
        let paused = SceneRunPolicy.isPaused(windowVisible: windowVisible, hostPaused: hostPaused)
        let effective = pose.effective(for: state, reduceMotion: reduceMotion)
        let beat = reduceMotion ? nil : reaction.flatMap { BookwormLook.beat($0.kind, for: state, gaze: effective.gaze) }
        let look = beat ?? .pose(effective)
        let activeTransition = reduceMotion || beat != nil || size.set == .small ? nil : transition
        let pair = activeTransition.flatMap { BookwormArt.transitionClip($0.kind) }
            ?? BookwormArt.clip(state, look: look, set: size.set)
        let start = beat != nil ? reaction?.startedAt : activeTransition?.startedAt

        VStack(alignment: alignment, spacing: CicadaTheme.spacingSM) {
            Group {
                if let pair, pair.1.order.count > 1, profile != .still, !paused {
                    let tracks = playbackTracks(clip: pair.1, startedAt: start, profile: profile)
                    TimelineView(SpriteFrameSchedule(tracks: tracks)) { context in
                        // TimelineView re-evaluates this closure only: the cover must be chosen here.
                        let cover = BookwormArt.coverIndex(at: context.date, profile: profile)
                        let current = activeTransition.flatMap { BookwormArt.transitionClip($0.kind) }
                            ?? BookwormArt.clip(state, look: look, cover: cover, set: size.set)
                        draw(current, at: context.date, startedAt: start, profile: profile, size: size)
                    }
                } else {
                    draw(pair, at: SpriteClock.origin, startedAt: nil, profile: .still, size: size)
                }
            }
            .frame(width: size.size.width, height: size.size.height)
            .background(WindowVisibilityReader { windowVisible = $0 })
            .accessibilityLabel("\(state.title) — \(state.detail)")
            if let caption {
                Text(caption).font(captionFont).foregroundStyle(captionColor)
            }
        }
    }

    private func playbackTracks(clip: SpriteClip, startedAt: Date?, profile: SpritePlaybackProfile) -> [SpriteFrameSchedule.Track] {
        var tracks: [SpriteFrameSchedule.Track] = [.init(origin: startedAt ?? SpriteClock.origin,
            seconds: clip.seconds.map { $0 * profile.slowdown }, loops: startedAt == nil)]
        // Reading poses and once beats also redraw at the cover boundary.
        if state.caseName == "reading", transition == nil,
           let idle = SpriteSheets.sheet(named: "bookworm-reading")?.clip("idle") {
            tracks.append(.init(origin: SpriteClock.origin, seconds: [idle.total * profile.slowdown], loops: true))
        }
        return tracks
    }

    @ViewBuilder
    private func draw(_ pair: (SpriteSheet, SpriteClip)?, at date: Date, startedAt: Date?,
                      profile: SpritePlaybackProfile, size: BookwormSize) -> some View {
        if let (sheet, clip) = pair {
            let step = startedAt.map { clip.onceStep(at: date, startedAt: $0, profile: profile) ?? max(0, clip.order.count - 1) }
                ?? clip.loopStep(at: date, profile: profile)
            if size.set == .small {
                Image(nsImage: BookwormRenderer.smallImage(state: state, frameStep: step, pointSize: size.size.width))
                    .interpolation(.none)
            } else if let cg = sheet.frameImage(clip.order[step]) {
                Image(decorative: cg, scale: 1).resizable().interpolation(.none)
            } else { Color.clear }
        } else { Color.clear }
    }
}
