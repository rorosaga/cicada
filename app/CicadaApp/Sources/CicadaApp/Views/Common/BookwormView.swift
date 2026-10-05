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
    var lighting: RoomLighting = .day
    var lampLit: Bool = false

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePaused) private var hostPaused
    @Environment(\.spriteSnapshotDate) private var snapshotDate
    @AppStorage(MascotPreference.defaultsKey) private var mascotRaw = MascotRegistry.bookworm.id
    @State private var windowVisible = true

    var body: some View {
        let mascot = MascotRegistry.resolve(mascotRaw)
        let size = BookwormSize.resolve(pointSize: pointSize, uiScale: CicadaTheme.uiScale, latticeCell: latticeCell)
        let profile = SpritePlaybackProfile.of(reduceMotion: reduceMotion, lowPower: SceneStore.shared.lowPower)
        let paused = snapshotDate != nil || SceneRunPolicy.isPaused(windowVisible: windowVisible, hostPaused: hostPaused)
        let effective = pose.effective(for: state, reduceMotion: reduceMotion)
        let beat = reduceMotion ? nil : reaction.flatMap { BookwormLook.beat($0.kind, for: state, gaze: effective.gaze) }
        let look = beat ?? .pose(effective)
        let activeTransition = reduceMotion || beat != nil || size.set == .small ? nil : transition
        let pair = activeTransition.flatMap { BookwormArt.transitionClip($0.kind, lighting: lighting, lampLit: lampLit, mascot: mascot) }
            ?? BookwormArt.clip(state, look: look, set: size.set, lighting: lighting, lampLit: lampLit, mascot: mascot)
        let start = beat != nil ? reaction?.startedAt : activeTransition?.startedAt

        VStack(alignment: alignment, spacing: CicadaTheme.spacingSM) {
            Group {
                if let pair, pair.1.order.count > 1, profile != .still, !paused {
                    let tracks = playbackTracks(clip: pair.1, startedAt: start, profile: profile, mascot: mascot)
                    // A layer swaps the frames; SwiftUI never re-renders the window for one (`SpriteLayerPlayer`).
                    SpriteLayerPlayer(tracks: tracks) { date in
                        // The player re-runs this closure only, once per boundary: the cover must be chosen here.
                        let cover = BookwormArt.coverIndex(at: date, profile: profile, mascot: mascot)
                        let current = activeTransition.flatMap { BookwormArt.transitionClip($0.kind, lighting: lighting, lampLit: lampLit, mascot: mascot) }
                            ?? BookwormArt.clip(state, look: look, cover: cover, set: size.set, lighting: lighting, lampLit: lampLit, mascot: mascot)
                        return image(current, at: date, startedAt: start, profile: profile, size: size, mascot: mascot)
                    }
                } else {
                    draw(pair, at: SpriteClock.origin, startedAt: nil, profile: .still, size: size, mascot: mascot)
                }
            }
            .frame(width: size.size.width, height: size.size.height)
            .background { if snapshotDate == nil { WindowVisibilityReader { windowVisible = $0 } } }
            .accessibilityElement(children: .ignore)
            .accessibilityAddTraits(.isImage)
            .accessibilityLabel("\(state.title) — \(state.detail)")
            if let caption {
                Text(caption).font(captionFont).foregroundStyle(captionColor)
            }
        }
    }

    private func playbackTracks(clip: SpriteClip, startedAt: Date?, profile: SpritePlaybackProfile,
                                mascot: Mascot) -> [SpriteFrameSchedule.Track] {
        var tracks: [SpriteFrameSchedule.Track] = [.init(origin: startedAt ?? SpriteClock.origin,
            seconds: clip.seconds.map { $0 * profile.slowdown }, loops: startedAt == nil)]
        // Reading poses and once beats also redraw at the cover boundary.
        if state.caseName == "reading", transition == nil,
           let idle = SpriteSheets.sheet(named: BookwormArt.sheetName(.reading, .room, mascot: mascot))?.clip("idle") {
            tracks.append(.init(origin: SpriteClock.origin, seconds: [idle.total * profile.slowdown], loops: true))
        }
        return tracks
    }

    /// A once beat holds its last frame; everything else loops on the shared clock.
    private static func step(_ clip: SpriteClip, at date: Date, startedAt: Date?, profile: SpritePlaybackProfile) -> Int {
        startedAt.map { clip.onceStep(at: date, startedAt: $0, profile: profile) ?? max(0, clip.order.count - 1) }
            ?? clip.loopStep(at: date, profile: profile)
    }

    /// The moving path's frame: the same choice `draw` makes, as the image a layer shows.
    private func image(_ pair: (SpriteSheet, SpriteClip)?, at date: Date, startedAt: Date?,
                       profile: SpritePlaybackProfile, size: BookwormSize, mascot: Mascot) -> CGImage? {
        guard let (sheet, clip) = pair else { return nil }
        let step = Self.step(clip, at: date, startedAt: startedAt, profile: profile)
        if size.set == .small {
            return BookwormRenderer.smallImage(state: state, frameStep: step, pointSize: size.size.width, mascot: mascot)
                .cgImage(forProposedRect: nil, context: nil, hints: nil)
        }
        return sheet.frameImage(clip.order[step])
    }

    @ViewBuilder
    private func draw(_ pair: (SpriteSheet, SpriteClip)?, at date: Date, startedAt: Date?,
                      profile: SpritePlaybackProfile, size: BookwormSize, mascot: Mascot) -> some View {
        if let (sheet, clip) = pair {
            let step = Self.step(clip, at: date, startedAt: startedAt, profile: profile)
            if size.set == .small {
                Image(nsImage: BookwormRenderer.smallImage(state: state, frameStep: step, pointSize: size.size.width, mascot: mascot))
                    .interpolation(.none)
            } else if let cg = sheet.frameImage(clip.order[step]) {
                Image(decorative: cg, scale: 1).resizable().interpolation(.none)
            } else { Color.clear }
        } else { Color.clear }
    }
}
