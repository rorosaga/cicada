import SwiftUI

/// The app's motion vocabulary (G137, spec R-M4) — the one place outside
/// `SleepMotion` where an animation duration is spelled.
///
/// Before this file, 47 `.animation(…)` / `withAnimation(…)` sites in 13
/// files each spelled their own literal and not one of them honoured Reduce
/// Motion — only the Sleep page did, through `SleepMotion`. Every function
/// here returns `nil` under Reduce Motion, which is SwiftUI for "jump to the
/// new value": the terminal frame, the same rule `SleepMotion` states.
/// `MotionLiteralLintTests` fails the build on a `duration` label anywhere
/// else, so a new literal cannot quietly skip that switch.
///
/// Named by curve, documented by use — a new call site picks by what it is
/// doing, not by what number looked right:
///
/// - `press` — easeOut 0.12 s: a button's press dip (`CicadaPlainButtonStyle`).
/// - `hover` — easeInOut 0.15 s: pointer hover fills, and short state fades
///   (selected, copied, asking, drag-over).
/// - `snap` — spring 0.2 s: a small in-place change (a row showing more
///   lines, a resolving flag, a strip collapsing).
/// - `standard` — spring 0.25 s: switching tabs, toggling a group.
/// - `panel` — spring 0.3 s: a card, panel or overlay arriving or leaving; a
///   list reflowing.
/// - `expand` — spring 0.3 s, bounce 0.15: an inbox card opening with give.
/// - `lift` — snappy 0.18 s: `hoverLift()`.
/// - `settle` — easeInOut 0.35 s: a value-driven bar (= `SleepMotion.settle`).
/// - `morph` — smooth 0.35 s: glass or matched-geometry shapes changing form.
enum CicadaMotion {
    /// The ceiling every transition here sits under — the same 400 ms budget
    /// `SleepMotion.maxDuration` holds for the Sleep page.
    static let maxDuration: TimeInterval = 0.4

    /// Was `CicadaPlainButtonStyle.pressAnimationDuration` (G83).
    static let pressDuration: TimeInterval = 0.12
    static let hoverDuration: TimeInterval = 0.15
    static let snapDuration: TimeInterval = 0.2
    static let standardDuration: TimeInterval = 0.25
    static let panelDuration: TimeInterval = 0.3
    static let expandDuration: TimeInterval = 0.3
    static let expandBounce: Double = 0.15
    static let liftDuration: TimeInterval = 0.18
    static let settleDuration: TimeInterval = 0.35
    static let morphDuration: TimeInterval = 0.35
    /// G136 — the ⌘K palette arriving (`snappy`, with a 0.98 → 1 scale) and
    /// leaving (fade), and a group's "Show all" (round-3 design §1.1).
    static let paletteInDuration: TimeInterval = 0.16
    static let paletteOutDuration: TimeInterval = 0.12
    static let groupExpandDuration: TimeInterval = 0.2
    /// G118 slice 2 (design §1.1): the Reader's cited-span wash fading in
    /// after it lands. Short — the eye is already moving to the words.
    static let spanRevealDuration: TimeInterval = 0.25

    /// G139 (design §1.1, R-O7) — a landed Settings row holds its wash, then fades.
    /// Under Reduce Motion the wash is held for both and removed with no fade.
    /// Deliberately outside `maxDuration` and NOT added to
    /// `CicadaMotionTests.testEveryDurationIsInsideTheBudget`: this is how long
    /// an emphasis lingers so the eye can find the row, not a transition
    /// between two layouts — the 400 ms budget is for the latter.
    static let rowHighlightHold: TimeInterval = 1.2
    static let rowHighlightFadeDuration: TimeInterval = 0.6

    /// Clouds drift, grass never moves (R-M6): at most 8 pt either way over a
    /// 60–120 s period — peripheral, never noticed as movement — at no more
    /// than 30 frames a second.
    static let ambientMaxAmplitude: CGFloat = 8
    static let ambientPeriodRange: ClosedRange<TimeInterval> = 60...120
    static let ambientDefaultPeriod: TimeInterval = 90
    static let ambientFrameInterval: TimeInterval = 1.0 / 30.0

    static func press(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .easeOut(duration: pressDuration) }
    static func hover(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .easeInOut(duration: hoverDuration) }
    static func snap(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .spring(duration: snapDuration) }
    static func standard(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .spring(duration: standardDuration) }
    static func panel(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .spring(duration: panelDuration) }
    static func expand(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .spring(duration: expandDuration, bounce: expandBounce)
    }
    static func lift(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .snappy(duration: liftDuration) }
    static func settle(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .easeInOut(duration: settleDuration) }
    static func morph(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .smooth(duration: morphDuration) }
    static func rowHighlightFade(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeOut(duration: rowHighlightFadeDuration)
    }
    static func paletteIn(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .snappy(duration: paletteInDuration) }
    static func paletteOut(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .easeOut(duration: paletteOutDuration) }
    static func groupExpand(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .snappy(duration: groupExpandDuration) }

    // Track I T4 (design §7). The drifting cloud reuses `ambientDefaultPeriod` /
    // `ambientMaxAmplitude` — two names for one value is the drift this file
    // exists to stop (R-IA18).
    /// Welcome rows reveal one after another (W1), at most this many staggered.
    static let revealStagger: TimeInterval = 0.04
    static let revealMaxRows = 8
    /// One nod of a brand mark on hover (`MarkHover`).
    static let markNodDuration: TimeInterval = 0.32
    /// The window-wide drop veil fading in (I1).
    static let dropVeilDuration: TimeInterval = 0.18
    /// The one-shot ✓ on a finished import (I6, W9).
    static let successDuration: TimeInterval = 0.4

    static func dropVeil(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .easeOut(duration: dropVeilDuration) }
    static func success(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .spring(duration: successDuration, bounce: 0.3)
    }
    /// Row `index` of a staggered reveal. Past `revealMaxRows` a row waits no
    /// longer than the eighth — capped, never dropped — so a long list never
    /// makes its last rows arrive seconds late.
    static func reveal(index: Int, reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeOut(duration: hoverDuration).delay(revealStagger * Double(min(index, revealMaxRows)))
    }
    /// `spanReveal` — the Reader's wash arriving on the cited sentence. nil
    /// under Reduce Motion: the wash is simply there (a static wash, §4.3).
    static func spanReveal(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeOut(duration: spanRevealDuration)
    }
}

// MARK: - Hover lift (R-M14)

/// For things that OPEN something — a card, a tile, an empty state's one
/// action. Never on dense rows (R9 §3.2: 20 jittering inbox rows), which keep
/// their `surfaceHover` fill change.
struct HoverLift: ViewModifier {
    /// Past ~1.02 text visibly softens mid-scale; past 2 pt it reads as a jump.
    static let maxScale: CGFloat = 1.02
    static let maxLift: CGFloat = 2

    var scale: CGFloat = 1.015
    var lift: CGFloat = 2

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    struct Pose: Equatable {
        var scale: CGFloat
        var lift: CGFloat
        var shadowOpacity: Double
        var shadowRadius: CGFloat
        var shadowY: CGFloat
    }

    /// Pure; tested. Scale and lift are motion and switch off under Reduce
    /// Motion; the deeper shadow is not motion and stays — so hover still
    /// reads for a person who asked for stillness.
    static func pose(hovering: Bool, reduceMotion: Bool, scale: CGFloat, lift: CGFloat) -> Pose {
        let moving = hovering && !reduceMotion
        return Pose(scale: moving ? min(scale, maxScale) : 1,
                    lift: moving ? min(lift, maxLift) : 0,
                    shadowOpacity: hovering ? 0.16 : 0.06,
                    shadowRadius: hovering ? 10 : 4,
                    shadowY: hovering ? 5 : 2)
    }

    func body(content: Content) -> some View {
        let pose = Self.pose(hovering: hovering, reduceMotion: reduceMotion, scale: scale, lift: lift)
        content
            .scaleEffect(pose.scale)
            .offset(y: -pose.lift)
            .shadow(color: .black.opacity(pose.shadowOpacity), radius: pose.shadowRadius, y: pose.shadowY)
            .animation(CicadaMotion.lift(reduceMotion: reduceMotion), value: hovering)
            .onHover { hovering = $0 }
    }
}

// MARK: - Icon hover (R-M13)

/// A glyph acknowledges the pointer once: a wiggle on macOS 15+ (`.wiggle`
/// is 15-only), a bounce on 14; and, when `selected` turns true, one bounce.
/// Never repeating — the one indefinite symbol motion in this app is a true
/// state (the Sleep pulse), not a hover.
///
/// Reduce Motion is enforced by never changing the trigger (`nextBump`), with
/// `symbolEffectsRemoved` inside the effects as a second guard: R9 could not
/// confirm symbol effects damp themselves, and `symbolEffectsRemoved` acts on
/// INHERITED effects, a direction that is easy to get backwards.
struct IconHover: ViewModifier {
    /// `nil`: track the glyph's own hover. Non-nil: the hover of a larger
    /// target the glyph sits in (a sidebar row).
    var hovering: Bool?
    var selected: Bool = false

    @State private var hoverBumps = 0
    @State private var selectBumps = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// Pure; tested. Wrapping add, so a very long session never traps.
    static func nextBump(_ current: Int, entering: Bool, reduceMotion: Bool) -> Int {
        entering && !reduceMotion ? current &+ 1 : current
    }

    func body(content: Content) -> some View {
        wiggle(content.symbolEffectsRemoved(reduceMotion))
            .symbolEffect(.bounce.up.byLayer, options: .nonRepeating, value: selectBumps)
            .onHover { inside in
                guard hovering == nil else { return }
                hoverBumps = Self.nextBump(hoverBumps, entering: inside, reduceMotion: reduceMotion)
            }
            .onChange(of: hovering ?? false) { _, now in
                hoverBumps = Self.nextBump(hoverBumps, entering: now, reduceMotion: reduceMotion)
            }
            .onChange(of: selected) { _, now in
                selectBumps = Self.nextBump(selectBumps, entering: now, reduceMotion: reduceMotion)
            }
    }

    /// `.wiggle` is macOS 15 API, and `#available` is only a runtime check:
    /// the symbol must exist in the SDK too (M1 final review, measured against
    /// MacOSX14.4: "type 'DiscreteSymbolEffect' has no member 'wiggle'"). The
    /// compile-time guard tests the SDK — SwiftUI's module version is 6.x from
    /// the 15 SDK on — so a macOS 14 SDK still builds, with the bounce.
    @ViewBuilder
    private func wiggle(_ view: some View) -> some View {
        #if canImport(SwiftUI, _version: 6.0)
        if #available(macOS 15, *) {
            view.symbolEffect(.wiggle.byLayer, options: .nonRepeating, value: hoverBumps)
        } else {
            bounce(view)
        }
        #else
        bounce(view)
        #endif
    }

    private func bounce(_ view: some View) -> some View {
        view.symbolEffect(.bounce.up.byLayer, options: .nonRepeating, value: hoverBumps)
    }
}

// MARK: - Mark hover (Track I T4, design §7)

/// A brand mark acknowledges the pointer once: rotate −5° → +3° → 0 and scale
/// 1 → 1.08 → 1 over `markNodDuration`. `symbolEffect` cannot animate a raster,
/// so this is a `keyframeAnimator` on the transform only — it never tints (Track
/// L: a vendor mark is never recoloured). Under Reduce Motion the nod is a 1 pt
/// accent ring while hovered: a cue, not motion. Lives here because its keyframes
/// spell durations, which only this file may (R-IA17). Apply it to the mark view
/// that already clips itself (`LogoImage.platformTile`), so the clip sits inside
/// the transform (design §14 item 4).
struct MarkHover: ViewModifier {
    /// `nil`: follow the mark's own hover; set: a larger target's (a row, a card).
    var hovering: Bool?

    @State private var ownHover = false
    @State private var nods = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    struct Pose: Equatable {
        var rotation: Double = 0
        var scale: CGFloat = 1
    }

    static let rotationKeys: [Double] = [-5, 3, 0]
    static let scaleKeys: [CGFloat] = [1.08, 1]

    /// Pure; tested. Wrapping add, like `IconHover.nextBump`.
    static func nextNod(_ current: Int, entering: Bool, reduceMotion: Bool) -> Int {
        entering && !reduceMotion ? current &+ 1 : current
    }

    static func showsRing(hovering: Bool, reduceMotion: Bool) -> Bool { hovering && reduceMotion }

    private var isHovering: Bool { hovering ?? ownHover }

    func body(content: Content) -> some View {
        content
            .keyframeAnimator(initialValue: Pose(), trigger: nods) { view, pose in
                view.rotationEffect(.degrees(pose.rotation)).scaleEffect(pose.scale)
            } keyframes: { _ in
                KeyframeTrack(\.rotation) {
                    LinearKeyframe(Self.rotationKeys[0], duration: CicadaMotion.markNodDuration * 0.3)
                    LinearKeyframe(Self.rotationKeys[1], duration: CicadaMotion.markNodDuration * 0.35)
                    LinearKeyframe(Self.rotationKeys[2], duration: CicadaMotion.markNodDuration * 0.35)
                }
                KeyframeTrack(\.scale) {
                    LinearKeyframe(Self.scaleKeys[0], duration: CicadaMotion.markNodDuration * 0.5)
                    LinearKeyframe(Self.scaleKeys[1], duration: CicadaMotion.markNodDuration * 0.5)
                }
            }
            .overlay {
                if Self.showsRing(hovering: isHovering, reduceMotion: reduceMotion) {
                    RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall, style: .continuous)
                        .stroke(CicadaTheme.accent, lineWidth: 1)
                }
            }
            .onHover { inside in
                guard hovering == nil else { return }
                ownHover = inside
                nods = Self.nextNod(nods, entering: inside, reduceMotion: reduceMotion)
            }
            .onChange(of: hovering ?? false) { _, now in
                nods = Self.nextNod(nods, entering: now, reduceMotion: reduceMotion)
            }
    }
}

extension View {
    /// See `HoverLift` — only on things that open something.
    func hoverLift(scale: CGFloat = 1.015, lift: CGFloat = 2) -> some View {
        modifier(HoverLift(scale: scale, lift: lift))
    }

    /// See `IconHover`. `iconHover()` follows the glyph's own hover;
    /// `iconHover(hovering: rowIsHovered, selected: isSelected)` a larger target's.
    func iconHover(hovering: Bool? = nil, selected: Bool = false) -> some View {
        modifier(IconHover(hovering: hovering, selected: selected))
    }

    /// See `MarkHover` — for brand marks (rasters); glyphs use `iconHover()`.
    func markHover(hovering: Bool? = nil) -> some View { modifier(MarkHover(hovering: hovering)) }
}
