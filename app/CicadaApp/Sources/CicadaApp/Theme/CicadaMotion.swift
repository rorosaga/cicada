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

    @ViewBuilder
    private func wiggle(_ view: some View) -> some View {
        if #available(macOS 15, *) {
            view.symbolEffect(.wiggle.byLayer, options: .nonRepeating, value: hoverBumps)
        } else {
            view.symbolEffect(.bounce.up.byLayer, options: .nonRepeating, value: hoverBumps)
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
}
