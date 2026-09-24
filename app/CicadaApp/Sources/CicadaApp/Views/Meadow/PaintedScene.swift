import SwiftUI

/// C10 (round-4 phase A contract; G144 part 2, G137) — the living painting: one component that draws a scene's
/// painting and its motion layers in a `SceneFraming`. Home's band, the Welcome and every onboarding pane are this
/// view, so there is one clock, one crossfade and one set of pause rules.
///
/// - **Which scene.** `time` pins one (a test, a page that wants a fixed light); `nil` follows Settings → General →
///   Scene over the clock (`HeroScenePreference`, `SceneStore`), never the theme (G144). A change — a pick, or the sun
///   crossing a line — crossfades the same composition: the new scene fades in over the old in 1.2 s, 0.6 s under
///   Reduce Motion, opacity only (R-HO4; owner, round-4 decision 8).
/// - **One clock** (R-HO7). One `TimelineView` at ≤ 30 fps drives every layer (15 under Low Power), paused while the
///   window cannot be seen, while the host says so (`paused`, or `\.scenePaused` — the shell sets it while the Welcome
///   covers Home) and absent off-tab, because Home is rebuilt per tab (R-IB3).
/// - **Gentler, never frozen** (DR-66). Reduce Motion or Low Power make the profile `.gentle`.
/// - **Paint only.** No word, number or control is ever drawn here (DR-13, DR-50); hidden from VoiceOver, never
///   hit-tested, and under Increase Contrast it steps back to 30 % like every Meadow decoration (R9 §7).
struct PaintedScene: View {
    let framing: SceneFraming
    private let pinned: SceneTime?
    private let hostPaused: Bool

    @AppStorage(HeroScenePreference.defaultsKey) private var sceneRaw = HeroScenePreference.automatic.rawValue
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorSchemeContrast) private var contrast
    @Environment(\.scenePaused) private var shellPaused
    @State private var fade: SceneCrossfadeState
    @State private var incomingOpacity: Double = 0
    @State private var windowVisible = true

    init(_ framing: SceneFraming, time: SceneTime? = nil, paused: Bool = false) {
        self.framing = framing
        pinned = time
        hostPaused = paused
        // Seeded here, never animated on mount (DR-65): the first frame is already the right scene.
        let stored = HeroScenePreference.stored(UserDefaults.standard.string(forKey: HeroScenePreference.defaultsKey))
        _fade = State(initialValue: SceneCrossfadeState(time ?? stored.time(clock: SceneStore.shared.time)))
    }

    private var target: SceneTime {
        pinned ?? HeroScenePreference.stored(sceneRaw).time(clock: SceneStore.shared.time)
    }

    var body: some View {
        let lowPower = SceneStore.shared.lowPower
        let profile = SceneProfile.of(reduceMotion: reduceMotion, lowPower: lowPower)
        let paused = SceneRunPolicy.isPaused(windowVisible: windowVisible, hostPaused: hostPaused || shellPaused)
        TimelineView(.animation(minimumInterval: SceneRunPolicy.frameInterval(lowPower: lowPower), paused: paused)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            ZStack {
                PaintedSceneFrame(framing: framing, time: fade.base, t: t, profile: profile)
                if let incoming = fade.incoming {
                    PaintedSceneFrame(framing: framing, time: incoming, t: t, profile: profile)
                        .opacity(incomingOpacity)
                }
            }
        }
        .modifier(SceneFramingChrome(framing: framing))
        .opacity(contrast == .increased ? MeadowRules.increasedContrastCeiling : 1)
        .background(WindowVisibilityReader { windowVisible = $0 })
        .onChange(of: target) { _, next in crossfade(to: next) }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private func crossfade(to next: SceneTime) {
        guard fade.begin(next) else { return }
        incomingOpacity = 0
        withAnimation(CicadaMotion.sceneCrossfade(reduceMotion: reduceMotion)) {
            incomingOpacity = 1
        } completion: {
            if fade.finish(next) { incomingOpacity = 0 }
        }
    }
}

/// The crossfade as values (R-HO4): `base` is drawn fully and `incoming` fades in over it — opacity only, over the same
/// composition, so a half-way frame never shows a doubled hill (ART_DIRECTION §3's crossfade test).
struct SceneCrossfadeState: Equatable {
    private(set) var base: SceneTime
    private(set) var incoming: SceneTime?

    init(_ time: SceneTime) { base = time }

    var target: SceneTime { incoming ?? base }

    /// Starts a fade to `next`; false when it is already the target. A pick mid-fade starts from the scene that was
    /// fading in, so the newest choice always fades in over the latest.
    mutating func begin(_ next: SceneTime) -> Bool {
        guard next != target else { return false }
        if let incoming { base = incoming }
        incoming = next
        return true
    }

    /// The fade to `time` ended; false, and nothing changes, when a newer fade replaced it.
    @discardableResult
    mutating func finish(_ time: SceneTime) -> Bool {
        guard incoming == time else { return false }
        base = time
        incoming = nil
        return true
    }
}

private struct ScenePausedKey: EnvironmentKey { static let defaultValue = false }

extension EnvironmentValues {
    /// A host's reason to rest every painting under it (R-HO7). The shell sets it while the Welcome covers Home, so a
    /// band nobody can see spends no frames; phase B's pages can set it on a page behind another.
    var scenePaused: Bool {
        get { self[ScenePausedKey.self] }
        set { self[ScenePausedKey.self] = newValue }
    }
}

/// `.hero(band:)` owns the band's height and its fade into the window (R-HO6); every framing clips to its frame.
private struct SceneFramingChrome: ViewModifier {
    let framing: SceneFraming

    func body(content: Content) -> some View {
        if case .hero(let band) = framing {
            content
                .frame(maxWidth: .infinity)
                .frame(height: CicadaTheme.scaled(band))
                .clipped()
                .mask(LinearGradient(stops: [.init(color: .black, location: SceneGeometry.bandFadeStart),
                                             .init(color: .clear, location: 1)],
                                     startPoint: .top, endPoint: .bottom))
        } else {
            content.clipped()
        }
    }
}

/// One instant of a scene — the unit `PaintedScene`'s clock redraws and the snapshot tests render. Back to front
/// (ART_DIRECTION §5): the plate, the light, stars (night), drifting clouds, the grass corners (hero only), then seeds
/// (day, afternoon) or fireflies (night). The whole stack is one camera: the breath scales and drifts it together.
struct PaintedSceneFrame: View {
    let framing: SceneFraming
    let time: SceneTime
    let t: TimeInterval
    let profile: SceneProfile

    var body: some View {
        GeometryReader { geo in
            let size = geo.size
            if let plate = MeadowArt.image(for: framing.plate, time: time) {
                let rect = SceneGeometry.plateRect(image: plate.size, container: size, framing: framing)
                let camera = SceneMotion.camera(at: t, container: size, profile: profile)
                ZStack(alignment: .topLeading) {
                    Image(nsImage: plate).resizable().interpolation(.high)
                        .frame(width: rect.width, height: rect.height)
                        .offset(x: rect.minX, y: rect.minY)
                    light(rect: rect, size: size)
                    if time == .night { stars(rect: rect) }
                    clouds(rect: rect, size: size)
                    if framing.hasGrassLayers {
                        grass(.left, plate: plate.size, rect: rect)
                        grass(.right, plate: plate.size, rect: rect)
                    }
                    particles(rect: rect)
                }
                .frame(width: size.width, height: size.height, alignment: .topLeading)
                .scaleEffect(camera.scale)
                .offset(x: camera.dx, y: camera.dy)
            } else if case .hero = framing {
                Color.clear   // a band that lost its painting is just the window
            } else {
                MeadowSky(phase: time.skyPhase)
            }
        }
        .clipped()
    }

    private func light(rect: CGRect, size: CGSize) -> some View {
        let light = SceneMotion.light(framing.composition, time: time, at: t, profile: profile)
        let center = UnitPoint(x: (rect.minX + light.center.x * rect.width) / max(size.width, 1),
                               y: (rect.minY + light.center.y * rect.height) / max(size.height, 1))
        return RadialGradient(colors: [ScenePaint.light(time).opacity(light.opacity), .clear], center: center,
                              startRadius: 0, endRadius: light.radius * rect.width)
            .blendMode(.softLight)
            .frame(width: size.width, height: size.height)
    }

    private func stars(rect: CGRect) -> some View {
        Canvas { context, _ in
            for star in SceneLayout.starTable[framing.composition] ?? [] {
                let center = CGPoint(x: rect.minX + star.x * rect.width, y: rect.minY + star.y * rect.height)
                context.fill(Path(ellipseIn: SceneGeometry.disc(center, star.radius)),
                             with: .color(ScenePaint.star.opacity(SceneMotion.twinkle(star, at: t, profile: profile))))
            }
        }
    }

    private func clouds(rect: CGRect, size: CGSize) -> some View {
        ForEach(SceneMotion.clouds(at: t, plate: rect, container: size, framing: framing, time: time,
                                   profile: profile), id: \.lane) { cloud in
            if let image = MeadowArt.image(for: cloud.art, time: time) {
                Image(nsImage: image).resizable().interpolation(.high)
                    .frame(width: cloud.frame.width, height: cloud.frame.height)
                    .opacity(cloud.opacity)
                    .offset(x: cloud.frame.minX, y: cloud.frame.minY)
            }
        }
    }

    @ViewBuilder
    private func grass(_ side: SceneGrassSide, plate: CGSize, rect: CGRect) -> some View {
        if let layer = MeadowArt.image(for: side.art, time: time) {
            let frame = SceneGeometry.grassRect(plate: rect, plateImage: plate, layerImage: layer.size, side: side)
            Image(nsImage: layer).resizable().interpolation(.high)
                .frame(width: frame.width, height: frame.height)
                .rotationEffect(.degrees(SceneMotion.grassAngle(side, at: t, profile: profile)), anchor: side.pivot)
                .offset(x: frame.minX, y: frame.minY)
        }
    }

    private func particles(rect: CGRect) -> some View {
        Canvas { context, _ in
            if time == .night {
                Self.drawFireflies(in: &context, composition: framing.composition, rect: rect, t: t, profile: profile)
            } else {
                Self.drawSeeds(in: &context, composition: framing.composition, rect: rect, t: t, profile: profile,
                               colour: time == .afternoon ? ScenePaint.seedAfternoon : ScenePaint.seed)
            }
        }
    }

    /// Split out of the `Canvas` closure: one closure holding both loops' mixed CGFloat/Double arithmetic is more
    /// than Swift 6.2's type checker solves "in reasonable time" (measured while the plan was reviewed).
    private static func drawFireflies(in context: inout GraphicsContext, composition: SceneComposition, rect: CGRect,
                                      t: TimeInterval, profile: SceneProfile) {
        for firefly in SceneLayout.fireflyTable[composition] ?? [] {
            let p = SceneMotion.firefly(firefly, at: t, plate: rect, profile: profile)
            let glow = ScenePaint.fireflyGlow.opacity(0.3 * p.opacity)
            let core = ScenePaint.fireflyCore.opacity(p.opacity)
            context.fill(Path(ellipseIn: SceneGeometry.disc(p.center, p.radius * 3)), with: .color(glow))
            context.fill(Path(ellipseIn: SceneGeometry.disc(p.center, p.radius)), with: .color(core))
        }
    }

    /// A soft disc and a three-stroke tuft, turned by the seed's tilt.
    private static func drawSeeds(in context: inout GraphicsContext, composition: SceneComposition, rect: CGRect,
                                  t: TimeInterval, profile: SceneProfile, colour: Color) {
        for seed in SceneLayout.seedTable[composition] ?? [] {
            let p = SceneMotion.seed(seed, at: t, plate: rect, profile: profile)
            let disc = colour.opacity(p.opacity)
            let strokes = colour.opacity(0.8 * p.opacity)
            context.fill(Path(ellipseIn: SceneGeometry.disc(p.center, p.radius)), with: .color(disc))
            context.stroke(tuft(at: p.center, tilt: p.tilt), with: .color(strokes), lineWidth: 0.6)
        }
    }

    /// Three 5 pt strokes fanned 28° apart around straight up, turned by `tilt` degrees.
    static func tuft(at center: CGPoint, tilt: Double) -> Path {
        var path = Path()
        for k in -1...1 {
            let radians: Double = (tilt + Double(k) * 28 - 90) * Double.pi / 180
            let end = CGPoint(x: center.x + CGFloat(5 * cos(radians)), y: center.y + CGFloat(5 * sin(radians)))
            path.move(to: center)
            path.addLine(to: end)
        }
        return path
    }
}
