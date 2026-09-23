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

/// "The pile, 3 sources" — the container names SOURCES, not a book total: the
/// sentence already says how many are waiting (R-Z7), and the old "N books on
/// the pile" was a second count of the same thing in a different noun.
func pileAccessibilityLabel(sourceCount: Int) -> String {
    "The pile, \(sourceCount) \(sourceCount == 1 ? "source" : "sources")"
}

/// A spine speaks its row's sentence (design I5) — one function, so the pile
/// and What's waiting can never describe one source two ways. The folded
/// remainder has no single row, so it says where its books are.
func spineAccessibilityLabel(spec: BookSpec, row: StudyRow?) -> String {
    guard let row, !spec.isRemainder else { return "\(spec.count) more on the pile, in Details" }
    return StudyListCard.rowAccessibilityLabel(row)
}

/// The spine's tooltip — its numbers with their nouns (I5). Also reachable by
/// click (the popover) and VoiceOver, so it is never hover-only (§11).
func spineHelp(spec: BookSpec, row: StudyRow?, locale: Locale = .autoupdatingCurrent) -> String {
    guard let row, !spec.isRemainder else { return spineAccessibilityLabel(spec: spec, row: row) }
    let state = queueRowState(row)
    switch state {
    case .waiting:
        return ([row.label, queueRowWords(state, locale: locale)]
                + (row.oldestAge.map { ["oldest \($0)"] } ?? [])).joined(separator: " · ")
    default:
        return "\(row.label) · \(queueRowWords(state, locale: locale))"
    }
}

/// The pile itself: bottom-aligned spines, the fattest book at the BOTTOM
/// like books actually stack — `bookPileLayout` hands the specs largest-first
/// (its own tested contract, and what the study list reads), so the view
/// reverses them for display rather than asking the layout to sort the
/// other way (owner-side check 2026-09-05: the first cut drew the biggest
/// spine on top, which read as a chart's bar order, not a pile). A spine
/// whose `widthFraction` is 0 (everything from that source has been read
/// this cycle) draws nothing rather than a zero-width sliver.
///
/// Track Z Z6 (§7.1): every spine is a control (`SpineButton`). The pile is a
/// `.contain` container named by its source count, so VoiceOver reaches each
/// spine inside it, largest first, whatever the bottom-up display order.
struct BookPileView: View {
    let books: [BookSpec]
    var rows: [StudyRow] = []
    var episodes: [EpisodeQueueItem] = []
    var room: RoomModel? = nil
    var onOpenDetails: (DetailsSection) -> Void = { _ in }

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// The gap above each spine — part of that spine's hit target (§6.2), so
    /// an 8 pt spine is still comfortable to click (Z-P14). It replaced the
    /// stack's own 2 pt spacing, which no spine owned.
    static let spineGap: CGFloat = 2
    static let maxSpineWidth: CGFloat = 150

    var body: some View {
        let byOrigin = Dictionary(rows.map { ($0.origin, $0) }, uniquingKeysWith: { first, _ in first })
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Self.stacked(books)) { spec in
                if spec.widthFraction > 0 {
                    SpineButton(spec: spec, row: byOrigin[spec.origin], episodes: episodes, room: room,
                                onOpenDetails: onOpenDetails)
                        // Inside the pile's own container: largest first (§11),
                        // whatever the bottom-up display order.
                        .accessibilitySortPriority(-Double(books.firstIndex(of: spec) ?? 0))
                }
            }
        }
        .frame(maxHeight: .infinity, alignment: .bottom)
        .animation(SleepMotion.pile(reduceMotion: reduceMotion), value: books)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(pileAccessibilityLabel(sourceCount: rows.count))
        .accessibilitySortPriority(RoomA11yOrder.spines)
    }

    /// Display order: `bookPileLayout`'s largest-first list, bottom-up — the
    /// remainder spine (always last in the layout) lands on the very bottom
    /// of the pile, under the real books, which is where a folded "+more"
    /// of small leftovers belongs. Pure and tested.
    static func stacked(_ books: [BookSpec]) -> [BookSpec] { Array(books.reversed()) }
}

/// One spine as a control (Track Z §7.1): a click opens its source's queue —
/// the folded remainder opens Details › What's waiting instead (Z-P20: it
/// folds several sources, so it has no one queue to show). Hover lifts it
/// 2 pt (a SwiftUI shape, not pixel art — R-Z4 is about the worm) and tints
/// its Details row through `room.hoveredOrigin` (I5, I7). No spine starts,
/// cancels or schedules a cycle (R-Z9).
struct SpineButton: View {
    let spec: BookSpec
    let row: StudyRow?
    let episodes: [EpisodeQueueItem]
    let room: RoomModel?
    let onOpenDetails: (DetailsSection) -> Void

    @State private var hovering = false
    @State private var showPopover = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let lifted = hovering || room?.hoveredOrigin == spec.origin
        Button {
            if spec.isRemainder || row == nil { onOpenDetails(.waiting) } else { showPopover = true }
        } label: {
            shape(lifted: lifted)
                .padding(.top, BookPileView.spineGap)
                .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { inside in
            hovering = inside
            room?.hover(origin: spec.origin, inside: inside)
        }
        .roomLinkCursor()
        .help(spineHelp(spec: spec, row: row))
        .accessibilityLabel(spineAccessibilityLabel(spec: spec, row: row))
        .popover(isPresented: $showPopover, arrowEdge: .trailing) {
            if let row {
                SpinePopover(row: row, episodes: episodes) {
                    showPopover = false
                    onOpenDetails(.waiting)
                }
            }
        }
    }

    private func shape(lifted: Bool) -> some View {
        let color = spec.isRemainder ? CicadaTheme.textTertiary.opacity(0.4) : OriginIconography.color(for: spec.origin)
        return ZStack(alignment: .leading) {
            RoundedRectangle(cornerRadius: 3)
                .fill(color)
                .frame(width: BookPileView.maxSpineWidth * spec.widthFraction, height: spec.height)
            if spec.height >= 14 {
                HStack(spacing: CicadaTheme.spacingXS) {
                    if !spec.isRemainder { OriginMark(origin: spec.origin, size: 12) }
                    Text("\(spec.count)")
                        .font(CicadaTheme.captionFont)
                        // Z-P19 / design defect 7 — a theme token, not a literal.
                        .foregroundStyle(CicadaTheme.onFill)
                }
                .padding(.horizontal, CicadaTheme.spacingXS)
            }
        }
        // Resting at 0.85 is today's look (the colour used to carry the
        // opacity); a lift is full strength, and 2 pt up unless Reduce Motion.
        .opacity(spec.isRemainder || lifted ? 1 : 0.85)
        .offset(y: lifted && !reduceMotion ? -2 : 0)
        .animation(SleepMotion.hover(reduceMotion: reduceMotion), value: lifted)
    }
}
