import QuartzCore
import SwiftUI

/// The Sleep page's live instrument: the five stages as one compact stepper (G125 v3 Task 5, R-A8, P15; redrawn
/// 2026-10-16, "center it and make it one calm group").
///
/// It used to be five 56 pt pixel-icon tiles with arrows between them, left-aligned in the column, each with the same
/// accent underline whatever its state, so done, current and to come read alike. Now it is one row that spans the
/// room's 760 pt column (DR-36) exactly as the progress bar under it does: a marker and a word per stage, joined by
/// connectors that stretch, so the first marker sits on the column's left edge and the last word on its right.
///
/// What each state looks like (`StepLook`, pure so `SleepRunStripTests` holds it):
/// - **done** — a check in a quiet disc, the word in `textSecondary`;
/// - **current** — an accent ring with a breathing accent dot inside (DR-5's focus-ring use: it marks where the
///   machine's attention is), the word in `textPrimary` medium;
/// - **to come / not reached** — an empty ring, the word in `textTertiary`;
/// - **failed** — the ring holds a `danger` cross; the word says nothing new, VoiceOver says "failed" (DR-7).
///
/// Three rules it keeps from the strip it replaced:
/// - **Only a counted stage carries a fill (P15).** `stageStripState` decides that; the fill is drawn on the connector
///   leaving the current stage — the way to the next one — and nowhere else.
/// - **A cancel or a failure freezes it where it stopped**, again in `stageStripState`.
/// - **No `TimelineView`.** The old strip breathed through a 0.1 s `TimelineView`, the pattern app.md measured laying
///   the whole window out at the display rate. The live dot breathes on its own layer (`LiveDot`), and Reduce Motion
///   holds it lit (R-A13, DR-66).
struct SleepStageStrip: View {
    /// Resolved by the caller from the same status reading the rest of the page uses (H1).
    let pips: [StagePip]

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// The marker's diameter before `uiScale`.
    static let markerSize: CGFloat = 14
    /// The shortest a connector may get; past it the words keep their size and the row is still one row.
    static let connectorMinLength: CGFloat = 12
    static let connectorHeight: CGFloat = 2

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            ForEach(Array(SleepStages.all.enumerated()), id: \.element.id) { index, stage in
                if index > 0 { connector(after: pip(at: index - 1)) }
                step(stage, pip: pip(at: index))
            }
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Copy.SleepV5.stagesLabel)
    }

    /// `stageStripState` always returns exactly five, but a short array draws the stages it knows rather than trap.
    private func pip(at index: Int) -> StagePip {
        index < pips.count ? pips[index] : .pending
    }

    // MARK: One stage

    private func step(_ stage: SleepStage, pip: StagePip) -> some View {
        let look = StepLook(pip)
        return HStack(spacing: CicadaTheme.spacingXS + 2) {
            marker(look)
            Text(stage.shortLabel)
                .font(CicadaTheme.font(size: 12, weight: look == .current ? .medium : .regular))
                .foregroundStyle(labelColor(look))
                .lineLimit(1)
                .fixedSize()
        }
        .help("\(stage.title): \(stage.detail)")
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Self.accessibilityLabel(stage, pip: pip))
    }

    /// What VoiceOver reads for one stage: its title and the pip's own word — from the pip, not the look, so a stage a
    /// stop never reached says "not reached" rather than "not started" (the two share the to-come look).
    static func accessibilityLabel(_ stage: SleepStage, pip: StagePip) -> String {
        "\(stage.title) — \(pip.accessibilityWord)"
    }

    private func labelColor(_ look: StepLook) -> Color {
        switch look {
        case .current: CicadaTheme.textPrimary
        case .done, .failed: CicadaTheme.textSecondary
        case .toCome: CicadaTheme.textTertiary
        }
    }

    @ViewBuilder
    private func marker(_ look: StepLook) -> some View {
        let size = CicadaTheme.scaled(Self.markerSize)
        ZStack {
            switch look {
            case .done:
                Circle().fill(CicadaTheme.bgBadge)
                Image(systemName: "checkmark")
                    .font(CicadaTheme.font(size: 8, weight: .bold))
                    .foregroundStyle(CicadaTheme.textSecondary)
            case .current:
                Circle().strokeBorder(CicadaTheme.accent, lineWidth: 1.5)
                LiveDot(diameter: size * 0.43)
            case .failed:
                Circle().strokeBorder(CicadaTheme.danger, lineWidth: 1.5)
                Image(systemName: "xmark")
                    .font(CicadaTheme.font(size: 7, weight: .bold))
                    .foregroundStyle(CicadaTheme.danger)
            case .toCome:
                Circle().strokeBorder(CicadaTheme.textTertiary.opacity(0.6), lineWidth: 1)
            }
        }
        .frame(width: size, height: size)
    }

    // MARK: The way between two stages

    /// Solid once the stage before it is done; filled to the stage's own fraction when it is the counted stage in
    /// flight (P15); a quiet track otherwise.
    private func connector(after pip: StagePip) -> some View {
        let height = CicadaTheme.scaled(Self.connectorHeight)
        let fill = StepLook.connectorFill(after: pip)
        return GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(CicadaTheme.bgBadge)
                Capsule().fill(CicadaTheme.textTertiary)
                    .frame(width: geo.size.width * fill)
            }
            .animation(SleepMotion.settle(reduceMotion: reduceMotion), value: fill)
        }
        .frame(minWidth: CicadaTheme.scaled(Self.connectorMinLength), maxWidth: .infinity)
        .frame(height: height)
        .accessibilityHidden(true)
    }
}

/// How one stage reads in the stepper — the four looks a pip collapses to.
enum StepLook: Equatable {
    case done
    case current
    case failed
    case toCome

    init(_ pip: StagePip) {
        switch pip {
        case .done: self = .done
        case .active: self = .current
        case .failed: self = .failed
        case .pending, .skipped: self = .toCome
        }
    }

    /// A representative pip, for the words VoiceOver reads.
    var pip: StagePip {
        switch self {
        case .done: .done
        case .current: .active(fill: nil)
        case .failed: .failed
        case .toCome: .pending
        }
    }

    /// How far the connector leaving a stage is drawn: whole after a done stage, the counted fraction after the
    /// stage in flight (never invented — `nil` draws none, P15), nothing otherwise.
    static func connectorFill(after pip: StagePip) -> Double {
        switch pip {
        case .done: 1
        case .active(let fill): min(1, max(0, fill ?? 0))
        case .pending, .skipped, .failed: 0
        }
    }
}

// MARK: - The live dot

/// The current stage's quiet live indicator: an accent dot that breathes on its own Core Animation layer, so a running
/// stage costs SwiftUI no redraw at all (the `SpriteLayerPlayer` rule, app.md). Reduce Motion, an `ImageRenderer`
/// snapshot (`spriteSnapshotDate`) and a platform view that cannot draw all get the plain lit dot.
struct LiveDot: View {
    let diameter: CGFloat
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.spriteSnapshotDate) private var snapshotDate

    var body: some View {
        if reduceMotion || snapshotDate != nil {
            Circle().fill(CicadaTheme.accent).frame(width: diameter, height: diameter)
        } else {
            BreathingDotLayer(color: NSColor(CicadaTheme.accent))
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
