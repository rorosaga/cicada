import SwiftUI

/// G125 R1/R9 — the Sleep page's ONE volume encoding: characters queued, per
/// source, on a log scale. Not a chart (R1 forbids bars-per-source, tiles,
/// an age histogram) — a pile of book spines is a glance, not a report.
struct OriginVolume: Equatable {
    let origin: String
    /// Episode count for this origin — used for `widthFraction`'s
    /// denominator and the remainder fold's count, never for height (chars
    /// alone drives height; a pile with one huge episode and a pile with
    /// many tiny ones should look different).
    let count: Int
    /// Total body characters across this origin's queued episodes — what
    /// `bookPileLayout` turns into spine height.
    let chars: Int
    /// How much of `count` is still unread. Equals `count` while idle (R9:
    /// nothing has been read yet, the whole pile is "remaining"); during a
    /// running cycle it is `queueByOrigin - readByOrigin`, clamped to
    /// `0...count`.
    let remaining: Int
}

/// One spine on the pile. `isRemainder` marks the single folded "+more"
/// spine `bookPileLayout` synthesizes when there are more buckets than
/// `maxBooks` — its `origin` is the literal `"+more"`, never a real one.
struct BookSpec: Identifiable, Equatable {
    let origin: String
    let count: Int
    let height: CGFloat
    let widthFraction: Double
    let isRemainder: Bool
    var id: String { origin }
}

/// Pure layout (R9): deterministic, no view, no dates. Height is
/// `8 + 6·log2(1 + chars/2000)` clamped to `8...40` — a `chars` of 0 still
/// draws the 8 pt floor (an episode with no body is still a book on the
/// pile, just a thin one). Sorted largest-first by `chars` (origin breaks a
/// tie) so the biggest pile always reads leftmost; anything past `maxBooks`
/// folds into one remainder spine sized from the SUM of what it absorbed,
/// so the pile's total visual mass never silently shrinks just because
/// there were more than `maxBooks` sources.
func bookPileLayout(_ buckets: [OriginVolume], maxBooks: Int = 8) -> [BookSpec] {
    let sorted = buckets.sorted { $0.chars != $1.chars ? $0.chars > $1.chars : $0.origin < $1.origin }
    func height(_ chars: Int) -> CGFloat {
        let h = 8 + 6 * log2(1 + Double(max(0, chars)) / 2000)
        return CGFloat(min(40, max(8, h)))
    }
    var out = sorted.prefix(maxBooks).map { b in
        BookSpec(origin: b.origin, count: b.count, height: height(b.chars),
                 widthFraction: b.count > 0 ? min(1, max(0, Double(b.remaining) / Double(b.count))) : 1,
                 isRemainder: false)
    }
    let rest = sorted.dropFirst(maxBooks)
    if !rest.isEmpty {
        out.append(BookSpec(origin: "+more", count: rest.reduce(0) { $0 + $1.count },
                            height: height(rest.reduce(0) { $0 + $1.chars }), widthFraction: 1, isRemainder: true))
    }
    return out
}

/// Groups the cycle's queued episodes into `OriginVolume`s. Sums `chars` and
/// counts per origin from `queued` itself (the only source of per-episode
/// body length); `remaining` prefers the live per-cycle dicts while
/// `running` — `queueByOrigin[origin] - readByOrigin[origin]`, clamped to
/// never go negative (a transient race between the two counters must never
/// draw a spine wider than the pile it's slicing) — and otherwise falls
/// back to the origin's full `count`: idle (nothing has been read, the
/// whole pile still stands) AND the case where `origin` is queued but not a
/// key of `queueByOrigin` at all — the episode cap left it out of this
/// cycle, same condition `studyRows` renders as "next cycle" rather than a
/// bogus "0 of 0" — so its spine stays full-width too, not zeroed out.
func originVolumes(
    queued: [EpisodeQueueItem],
    queueByOrigin: [String: Int],
    readByOrigin: [String: Int],
    running: Bool
) -> [OriginVolume] {
    var charsByOrigin: [String: Int] = [:]
    var countByOrigin: [String: Int] = [:]
    var order: [String] = []
    for ep in queued {
        if charsByOrigin[ep.origin] == nil { order.append(ep.origin) }
        charsByOrigin[ep.origin, default: 0] += ep.chars
        countByOrigin[ep.origin, default: 0] += 1
    }
    return order.map { origin in
        let count = countByOrigin[origin] ?? 0
        let remaining: Int
        if running, let queuedForCycle = queueByOrigin[origin] {
            let readForCycle = readByOrigin[origin] ?? 0
            remaining = max(0, queuedForCycle - readForCycle)
        } else {
            remaining = count
        }
        return OriginVolume(origin: origin, count: count, chars: charsByOrigin[origin] ?? 0, remaining: remaining)
    }
}

/// The pile itself: bottom-aligned spines, tallest visual weight toward the
/// bottom of the frame like books actually stack. A spine whose
/// `widthFraction` is 0 (everything from that source has been read this
/// cycle) draws nothing rather than a zero-width sliver.
struct BookPileView: View {
    let books: [BookSpec]
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private static let maxSpineWidth: CGFloat = 150

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(books) { spec in
                if spec.widthFraction > 0 {
                    spine(spec)
                }
            }
        }
        .frame(maxHeight: .infinity, alignment: .bottom)
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.4), value: books)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(books.reduce(0) { $0 + $1.count }) books on the pile")
    }

    @ViewBuilder
    private func spine(_ spec: BookSpec) -> some View {
        let color = spec.isRemainder ? CicadaTheme.textTertiary.opacity(0.4)
                                      : OriginIconography.color(for: spec.origin).opacity(0.85)
        ZStack(alignment: .leading) {
            RoundedRectangle(cornerRadius: 3)
                .fill(color)
                .frame(width: Self.maxSpineWidth * spec.widthFraction, height: spec.height)
            if spec.height >= 14 {
                HStack(spacing: CicadaTheme.spacingXS) {
                    if !spec.isRemainder {
                        OriginMark(origin: spec.origin, size: 12)
                    }
                    Text("\(spec.count)")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(.white)
                }
                .padding(.horizontal, CicadaTheme.spacingXS)
            }
        }
    }
}
