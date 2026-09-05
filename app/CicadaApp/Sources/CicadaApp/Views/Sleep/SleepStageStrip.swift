import SwiftUI

/// The Sleep page's live instrument (G125 v3 Task 5 — spec R-A8, plan P15).
///
/// It **substitutes into the meter's slot**; it is not a sixth card. What it
/// replaced was `moodDetailLine`'s `Text("Stage \(stage) of 5")` plus a bare
/// linear `ProgressView` whose value was `stage / totalStages` — a bar that
/// moved in five jumps and named nothing. The strip says the same thing with
/// the five stage names visible at once, so a person can see which stage is
/// running AND what that stage does without opening the `?` popover.
///
/// Three rules it exists to keep:
///
/// - **Only Read carries a fill (P15).** `stageStripState` decides that; this
///   view just draws what it is handed, so there is no second place where a
///   fraction could be invented for a stage that has no per-episode unit.
/// - **A cancel or a failure freezes the strip where it stopped**, again in
///   `stageStripState` — the view never resets anything.
/// - **One `TimelineView`, and only while something is actually active.** The
///   caught-up worm is drawn through `BookwormRenderer.cachedImage` directly
///   rather than through `BookwormView` for exactly this reason: a second
///   `TimelineView` on an idle page would tick forever to animate a worm that
///   is meant to read as "nothing to do". That is also why the snapping
///   `BookwormView` normally does has to happen here by hand (G130 R6).
struct SleepStageStrip: View {
    /// Resolved by the caller from the same status reading the rest of the
    /// page uses (H1), so the strip can never disagree with the hero meter
    /// about how far the cycle got.
    let pips: [StagePip]
    /// R-A8's right end — see `stageStripShowsCaughtUpWorm`.
    var showsCaughtUpWorm: Bool = false

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// A fixed origin so the breath's phase never depends on when the view
    /// appeared — the same reason `BookwormView` pins one.
    static let timelineOrigin = Date(timeIntervalSinceReferenceDate: 0)

    /// The icons' requested point size, before `uiScale` and the 16-cell snap.
    static let iconPointSize: CGFloat = 32
    /// The caught-up worm's, before `uiScale` and the 24-cell snap.
    static let wormPointSize: CGFloat = 48

    private var hasActivePip: Bool {
        pips.contains { if case .active = $0 { return true } else { return false } }
    }

    var body: some View {
        // Ticking only while a stage is actually running keeps an idle page at
        // zero redraws; Reduce Motion pins the terminal frame either way, so
        // there is nothing for a timeline to drive then.
        if hasActivePip && !reduceMotion {
            TimelineView(.periodic(from: Self.timelineOrigin,
                                   by: SleepStages.pulsePeriod / Double(SleepStages.pulseSteps))) { context in
                strip(pulse: stagePulse(at: context.date, reduceMotion: false))
            }
        } else {
            strip(pulse: stagePulse(at: Self.timelineOrigin, reduceMotion: true))
        }
    }

    private func strip(pulse: Double) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            ForEach(Array(SleepStages.all.enumerated()), id: \.element.id) { index, stage in
                if index > 0 { arrow }
                stageCell(stage, pip: pip(at: index), pulse: pulse)
            }
            if showsCaughtUpWorm {
                caughtUpWorm
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .contain)
    }

    /// `stageStripState` always returns exactly five, but this view must not
    /// trap if a caller ever hands it fewer — a strip that renders the stages
    /// it knows about is strictly better than a crash on a page whose whole
    /// job is telling you what is happening.
    private func pip(at index: Int) -> StagePip {
        index < pips.count ? pips[index] : .pending
    }

    private var arrow: some View {
        Image(systemName: "arrow.right")
            .font(CicadaTheme.font(size: 9, weight: .semibold))
            .foregroundStyle(CicadaTheme.textTertiary.opacity(0.6))
            .padding(.top, CicadaTheme.spacingMD)
            .accessibilityHidden(true)
    }

    // MARK: One stage

    private func stageCell(_ stage: SleepStage, pip: StagePip, pulse: Double) -> some View {
        let iconPt = PixelRenderer.snappedPointSize(Self.iconPointSize * CicadaTheme.uiScale,
                                                    gridSize: StageIconSprites.size)
        return VStack(spacing: CicadaTheme.spacingXS) {
            Image(nsImage: PixelRenderer.cachedImage(
                key: Self.iconCacheKey(stage, pointSize: iconPt),
                grid: StageIconSprites.grid(for: stage),
                gridSize: StageIconSprites.size,
                pointSize: iconPt,
                palette: DeskPalette.ns))
                .interpolation(.none)
                .frame(width: iconPt, height: iconPt)
                // A stage that never ran is dimmed, not hidden: the pipeline
                // is the same five steps whether or not tonight reached them.
                .opacity(isLive(pip) ? 1 : 0.45)

            Text(stage.shortLabel)
                .font(CicadaTheme.font(size: 10, weight: .semibold))
                .foregroundStyle(isLive(pip) ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)

            pipBar(pip, pulse: pulse)
        }
        .frame(width: max(iconPt, 44))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(stage.title) — \(pip.accessibilityWord)")
    }

    private func isLive(_ pip: StagePip) -> Bool {
        switch pip {
        case .done, .active, .failed: true
        case .pending, .skipped: false
        }
    }

    /// The pip itself: a short track that a fraction can fill. A capsule
    /// rather than a dot precisely because **Read** has a real fraction to
    /// show (`read / total`), and a partially-filled dot at this size is
    /// unreadable. Every other stage fills the track whole or not at all —
    /// which is what "no per-episode unit" looks like, honestly drawn.
    private func pipBar(_ pip: StagePip, pulse: Double) -> some View {
        let width: CGFloat = 26 * CicadaTheme.uiScale
        let height: CGFloat = 4 * CicadaTheme.uiScale
        return ZStack(alignment: .leading) {
            Capsule()
                .fill(CicadaTheme.surfaceElevated)
                .frame(width: width, height: height)
            switch pip {
            case .done:
                Capsule().fill(CicadaTheme.accent).frame(width: width, height: height)
            case .active(let fill):
                // `nil` fill = running with no honest fraction: the whole track
                // breathes rather than showing a made-up length.
                Capsule()
                    .fill(CicadaTheme.accent)
                    .frame(width: fill.map { width * CGFloat(min(1, max(0, $0))) } ?? width,
                           height: height)
                    .opacity(pulse)
            case .failed:
                Capsule().fill(CicadaTheme.danger).frame(width: width, height: height)
            case .pending, .skipped:
                EmptyView()
            }
        }
        .animation(SleepMotion.settle(reduceMotion: reduceMotion), value: activeFillWidthKey)
    }

    /// The value the fill animates on — an `Equatable` scalar rather than the
    /// pip itself, so the bar eases between two Read fractions but does not
    /// re-run the animation on every breath tick.
    private var activeFillWidthKey: Double {
        for pip in pips {
            if case .active(let fill) = pip { return fill ?? -1 }
        }
        return -2
    }

    // MARK: The caught-up worm

    /// R-A8: the `.happy` worm at the right end when there is nothing waiting.
    /// Rendered through `BookwormRenderer.cachedImage` at a hand-snapped size
    /// (G130 R6) rather than through `BookwormView` — see this type's
    /// docstring for why a second `TimelineView` would be wrong here. Frame 1
    /// is the settled frame of the `happy` loop.
    ///
    /// Hidden from accessibility: the hero's qualifier chip already says
    /// "caught up" in words, and reading the mood twice buries the strip.
    private var caughtUpWorm: some View {
        let pt = BookwormRenderer.snappedPointSize(Self.wormPointSize * CicadaTheme.uiScale)
        return Image(nsImage: BookwormRenderer.cachedImage(state: .happy, frameIndex: 1, pointSize: pt))
            .interpolation(.none)
            .frame(width: pt, height: pt)
            .padding(.leading, CicadaTheme.spacingSM)
            .accessibilityHidden(true)
    }

    /// Namespaced for `PixelRenderer`'s shared scene cache (P13): whoever asks
    /// for an image owns its identity, and two callers sharing a key would
    /// share an image.
    static func iconCacheKey(_ stage: SleepStage, pointSize: CGFloat) -> String {
        "stage.\(stage.id)|\(Int(pointSize))"
    }
}
