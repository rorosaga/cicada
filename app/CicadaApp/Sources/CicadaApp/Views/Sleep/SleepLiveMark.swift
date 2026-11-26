import QuartzCore
import SwiftUI

// The run object's two live marks, both breathing on their own Core Animation layer (2026-11-26; the stage stepper
// they used to belong to retired the same day). Neither goes through a `TimelineView` — the pattern app.md measured
// laying the whole window out at the display rate — and Reduce Motion, an `ImageRenderer` snapshot
// (`spriteSnapshotDate`) and a platform view that cannot draw all get the held, lit frame (R-A13, DR-66).

// MARK: - The live dot

/// The running step's quiet live indicator: a dot in `color` (ink by default; the accent is DR-5's six uses, and "the
/// machine is working" is not one) that breathes on its own Core Animation layer, so a running
/// stage costs SwiftUI no redraw at all (the `SpriteLayerPlayer` rule, app.md). Reduce Motion, an `ImageRenderer`
/// snapshot (`spriteSnapshotDate`) and a platform view that cannot draw all get the plain lit dot.
struct LiveDot: View {
    let diameter: CGFloat
    var color: Color = CicadaTheme.textPrimary
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.spriteSnapshotDate) private var snapshotDate

    var body: some View {
        if reduceMotion || snapshotDate != nil {
            Circle().fill(color).frame(width: diameter, height: diameter)
        } else {
            BreathingDotLayer(color: NSColor(color))
                .frame(width: diameter, height: diameter)
        }
    }

    /// The breath: opacity between `SleepStages.pulseFloor` and fully lit over one `SleepStages.pulsePeriod`, eased,
    /// forever. `nil` under Reduce Motion — the held, fully lit frame (R-A13). Pure, so the motion budget is a test.
    static func breath(reduceMotion: Bool) -> CABasicAnimation? {
        guard !reduceMotion else { return nil }
        let breath = CABasicAnimation(keyPath: "opacity")
        breath.fromValue = 1.0
        breath.toValue = SleepStages.pulseFloor
        breath.duration = SleepMotion.liveBreathHalfPeriod
        breath.autoreverses = true
        breath.repeatCount = .infinity
        breath.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
        breath.isRemovedOnCompletion = false
        return breath
    }
}

private struct BreathingDotLayer: NSViewRepresentable {
    let color: NSColor

    func makeNSView(context: Context) -> DotView {
        let view = DotView()
        view.color = color
        return view
    }

    func updateNSView(_ view: DotView, context: Context) {
        view.color = color
    }

    /// A round layer that keeps its breath across SwiftUI updates; only a re-mount (a new current stage) restarts it.
    final class DotView: NSView {
        var color: NSColor = .clear { didSet { needsLayout = true } }

        override init(frame: NSRect) {
            super.init(frame: frame)
            wantsLayer = true
        }

        required init?(coder: NSCoder) { nil }

        override func viewDidChangeEffectiveAppearance() {
            super.viewDidChangeEffectiveAppearance()
            needsLayout = true
        }

        override func layout() {
            super.layout()
            guard let layer else { return }
            // A dynamic colour resolves against the view's own appearance, not whatever is current during layout.
            effectiveAppearance.performAsCurrentDrawingAppearance { layer.backgroundColor = color.cgColor }
            layer.cornerRadius = min(bounds.width, bounds.height) / 2
            if layer.animation(forKey: "breath") == nil, let breath = LiveDot.breath(reduceMotion: false) {
                layer.add(breath, forKey: "breath")
            }
        }
    }
}


/// The bar of a run with nothing countable (the old single-pass shape, `drain == nil`): a faint full-width track that
/// breathes at the same period as the dot. It is not a fraction and never reads as one (P15) — the dot and the track say
/// "working", the word says what — and it holds still under Reduce Motion and in a snapshot.
struct BreathingBar: View {
    /// How strong the track is at its lit frame: well under a fill, so it never reads as a bar that has been filled.
    static let level = 0.3
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.spriteSnapshotDate) private var snapshotDate

    var body: some View {
        if reduceMotion || snapshotDate != nil {
            Capsule().fill(CicadaTheme.textTertiary.opacity(Self.level))
        } else {
            BreathingBarLayer(color: NSColor(CicadaTheme.textTertiary.opacity(Self.level)))
        }
    }
}

private struct BreathingBarLayer: NSViewRepresentable {
    let color: NSColor

    func makeNSView(context: Context) -> BarView {
        let view = BarView()
        view.color = color
        return view
    }

    func updateNSView(_ view: BarView, context: Context) { view.color = color }

    final class BarView: NSView {
        var color: NSColor = .clear { didSet { needsLayout = true } }

        override init(frame: NSRect) {
            super.init(frame: frame)
            wantsLayer = true
        }

        required init?(coder: NSCoder) { nil }

        override func viewDidChangeEffectiveAppearance() {
            super.viewDidChangeEffectiveAppearance()
            needsLayout = true
        }

        override func layout() {
            super.layout()
            guard let layer else { return }
            effectiveAppearance.performAsCurrentDrawingAppearance { layer.backgroundColor = color.cgColor }
            layer.cornerRadius = min(bounds.width, bounds.height) / 2
            if layer.animation(forKey: "breath") == nil, let breath = LiveDot.breath(reduceMotion: false) {
                layer.add(breath, forKey: "breath")
            }
        }
    }
}
