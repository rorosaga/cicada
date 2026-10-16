import AppKit
import SwiftUI

/// G125 R1/R9 — the Sleep page's ONE volume encoding: one book per waiting source, its thickness stepped by how many
/// are waiting (owner pick "A · Stack", 2026-10-16). Not a chart (R1 forbids bars-per-source, tiles, an age
/// histogram) — a pile of books is a glance, not a report.
struct OriginVolume: Equatable {
    let origin: String
    /// Episode count for this origin — the book's thickness step and the count on its plate.
    let count: Int
    /// Total body characters across this origin's queued episodes — breaks a tie in the pile's order.
    let chars: Int
    /// How much of `count` is still unread. Equals `count` while idle (R9:
    /// nothing has been read yet, the whole pile is "remaining"); during a
    /// running cycle it is `queueByOrigin - readByOrigin`, clamped to
    /// `0...count`.
    let remaining: Int
}

/// One book on the pile. `isRemainder` marks the single folded "+N" book `bookPileLayout` (or the stack, when the
/// column is full) makes of what does not get a book of its own — its `origin` is the literal `"+more"`.
struct BookSpec: Identifiable, Equatable {
    let origin: String
    let count: Int
    /// Still unread this cycle; a book read through (`0`) is not drawn.
    let remaining: Int
    let isRemainder: Bool
    var id: String { origin }

    init(origin: String, count: Int, remaining: Int? = nil, isRemainder: Bool = false) {
        self.origin = origin
        self.count = count
        self.remaining = max(0, min(count, remaining ?? count))
        self.isRemainder = isRemainder
    }

    static func remainder(of folded: [BookSpec]) -> BookSpec {
        BookSpec(origin: "+more", count: folded.reduce(0) { $0 + $1.count },
                 remaining: folded.reduce(0) { $0 + $1.remaining }, isRemainder: true)
    }
}

/// Pure (R9): largest first by count (characters, then origin, break a tie), and anything past `maxBooks` folded into
/// one remainder book carrying the SUM of what it absorbed, so the pile's mass never silently shrinks.
func bookPileLayout(_ buckets: [OriginVolume], maxBooks: Int = PileBooks.maxBooks) -> [BookSpec] {
    let sorted = buckets.sorted {
        $0.count != $1.count ? $0.count > $1.count : $0.chars != $1.chars ? $0.chars > $1.chars : $0.origin < $1.origin
    }
    var out = sorted.prefix(maxBooks).map { BookSpec(origin: $0.origin, count: $0.count, remaining: $0.remaining) }
    let rest = sorted.dropFirst(maxBooks)
    if !rest.isEmpty {
        out.append(.remainder(of: rest.map { BookSpec(origin: $0.origin, count: $0.count, remaining: $0.remaining) }))
    }
    return out
}

/// A book placed in the pile's column, in whole cells from the column's bottom-left corner.
struct PlacedBook: Identifiable, Equatable {
    let spec: BookSpec
    let kind: BookKind
    let step: Int
    let x: Int
    let y: Int
    let width: Int
    var rows: Int { BookArt.rows[step] }
    var id: String { spec.id }
}

/// The count's ground on a book's spine: whole cells from the column's bottom-left corner, filled with the page ground
/// so the number never sits on the art (DR-13). `showsMark` — the source's mark fits beside the count.
struct BookPlate: Equatable {
    let x: Int
    let y: Int
    let width: Int
    let height: Int
    let showsMark: Bool
}

/// The stack (owner pick "A · Stack", 2026-10-16): books lying flat, the fattest at the bottom, right-aligned in the
/// pile's column and each nudged a cell or two so it reads as a pile someone made. A stack never passes
/// `maxStackRows`; past it a second, narrower stack stands to its left, and what neither holds folds into one "+N"
/// book. Everything is whole cells inside the column, so the pile is crisp and inside the painted room at every scale.
enum PileBooks {
    /// Real books before the fold.
    static let maxBooks = 7
    static let columnWidth = DeskScene.pileCell.width
    static let columnHeight = DeskScene.pileCell.height
    /// The books stand two cells up the floor, clear of the floor fade's darkest cells.
    static let base = 2
    /// The books' right edge: four columns short of the column's, clear of the room's corner post.
    static let rightEdge = DeskScene.pileCell.width - 4
    static let maxStackRows = 40
    static let wide: [BookKind: Int] = [.chat: 40, .message: 36, .page: 38, .note: 34, .video: 37, .other: 32]
    static let narrow: [BookKind: Int] = [.chat: 21, .message: 19, .page: 20, .note: 18, .video: 19, .other: 18]
    static let nudges = [0, 2, 1, 3]
    static let narrowNudges = [[0, 1, 0, 1], [1, 0, 1, 0]]
    /// The left stack's right edge: the right stack's widest book and largest nudge, then one clear column.
    static var leftStackEdge: Int { rightEdge - (narrow.values.max() ?? 0) - 1 - 1 }

    static func rows(_ spec: BookSpec) -> Int { BookArt.rows[BookArt.step(count: spec.count)] }

    static func stack(_ books: [BookSpec]) -> [PlacedBook] {
        let drawn = books.filter { $0.remaining > 0 }
        let total = drawn.reduce(0) { $0 + rows($1) }
        let two = total > maxStackRows
        var stacks: [[BookSpec]] = [[], []]
        var heights = [0, 0]
        var folded: [BookSpec] = drawn.filter(\.isRemainder)
        for book in drawn where !book.isRemainder {
            let t = rows(book)
            if let i = (0..<2).first(where: { heights[$0] + t <= maxStackRows }) {
                stacks[i].append(book)
                heights[i] += t
            } else {
                folded.append(book)
            }
        }
        if !folded.isEmpty {
            // The fold lies on the left stack (the only one, without a second); a book it does not fit beside is
            // folded into it too, so the "+N" is always drawn.
            let target = two ? 1 : 0
            var fold = BookSpec.remainder(of: folded)
            while heights[target] + rows(fold) > maxStackRows, let last = stacks[target].popLast() {
                heights[target] -= rows(last)
                fold = .remainder(of: [fold, last])
            }
            stacks[target].append(fold)
        }
        var out: [PlacedBook] = []
        for (i, stack) in stacks.enumerated() {
            var y = base
            for (j, book) in stack.enumerated() {
                let kind = book.isRemainder ? .other : bookKind(for: book.origin)
                let width = (two ? narrow : wide)[kind] ?? 32
                let nudge = two ? narrowNudges[i][j % 4] : nudges[j % 4]
                let right = i == 0 ? rightEdge : leftStackEdge
                out.append(PlacedBook(spec: book, kind: kind, step: BookArt.step(count: book.count),
                                      x: right - nudge - width, y: y, width: width))
                y += rows(book)
            }
        }
        return out
    }

    // MARK: The plate

    /// The plate starts after the spine's left band and ends before the hinge and page block.
    static let plateLead = 3
    static let plateTrail = 5
    /// What the plate holds at 1×: a 12 pt mark and an 11 pt count, 15 pt tall, 3 pt in from each end, 4 pt apart.
    static let platePoints: CGFloat = 15
    static let platePad: CGFloat = 3
    static let markPoints: CGFloat = 12
    static let markGap: CGFloat = 4

    static func label(_ spec: BookSpec) -> String { spec.isRemainder ? "+\(spec.count)" : "\(spec.count)" }

    /// The count's width in the caption face at `uiScale` (monospaced digits, medium).
    static func labelWidth(_ text: String, uiScale: Double) -> CGFloat {
        let font = NSFont.monospacedDigitSystemFont(ofSize: 11 * CGFloat(uiScale), weight: .medium)
        return ceil((text as NSString).size(withAttributes: [.font: font]).width)
    }

    /// The plate for `book` at `cell` points per cell, or nil when it does not fit inside the book's outline: then the
    /// count lives where it always does — the tooltip, the popover and the Waiting tab. The mark goes first.
    static func plate(for book: PlacedBook, cell: CGFloat, uiScale: Double) -> BookPlate? {
        plate(for: book, cell: cell, uiScale: uiScale, labelWidth: labelWidth(label(book.spec), uiScale: uiScale))
    }

    static func plate(for book: PlacedBook, cell: CGFloat, uiScale: Double, labelWidth: CGFloat) -> BookPlate? {
        let s = CGFloat(uiScale)
        func cells(_ points: CGFloat) -> Int { Int((points / cell - 0.001).rounded(.up)) }
        let height = cells(platePoints * s)
        guard height <= book.rows - 2 else { return nil }
        let room = book.width - plateLead - plateTrail
        let bare = cells((2 * platePad) * s + labelWidth)
        let marked = cells((2 * platePad + markPoints + markGap) * s + labelWidth)
        let y = book.y + (book.rows - height) / 2
        if !book.spec.isRemainder, marked <= room {
            return BookPlate(x: book.x + plateLead, y: y, width: marked, height: height, showsMark: true)
        }
        guard bare <= room else { return nil }
        return BookPlate(x: book.x + plateLead, y: y, width: bare, height: height, showsMark: false)
    }
}

/// Groups the cycle's queued episodes into `OriginVolume`s. Sums `chars` and
/// counts per origin from `queued` itself (the only source of per-episode
/// body length); `remaining` prefers the live per-cycle dicts while
/// `running` — `queueByOrigin[origin] - readByOrigin[origin]`, clamped to
/// never go negative (a transient race between the two counters must never
/// leave a book on the pile with nothing left in it) — and otherwise falls
/// back to the origin's full `count`: idle (nothing has been read, the
/// whole pile still stands) AND the case where `origin` is queued but not a
/// key of `queueByOrigin` at all — the episode cap left it out of this
/// cycle, same condition `studyRows` renders as "next cycle" rather than a
/// bogus "0 of 0" — so its book stays on the pile too.
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
    guard let row, !spec.isRemainder else { return "\(spec.count) more on the pile, in Waiting" }
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

/// The pile itself (owner pick "A · Stack", 2026-10-16): pixel-art books on the room's lattice, each a control
/// (Track Z §7.1), placed by `PileBooks.stack` in whole cells of the column the room reserves. The pile is a
/// `.contain` container named by its source count, so VoiceOver reaches each book inside it, largest first.
struct BookPileView: View {
    let books: [BookSpec]
    var rows: [StudyRow] = []
    var episodes: [EpisodeQueueItem] = []
    var room: RoomModel? = nil
    var onOpenDetails: (DetailsSection) -> Void = { _ in }
    /// The room the pile stands in; its column and cell place every book.
    let layout: DeskSceneLayout
    /// The room's lighting: a dark room draws each book's night frame.
    var night = false

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let byOrigin = Dictionary(rows.map { ($0.origin, $0) }, uniquingKeysWith: { first, _ in first })
        let cell = layout.cell
        ZStack(alignment: .bottomLeading) {
            Color.clear
            ForEach(PileBooks.stack(books)) { book in
                PileBookButton(book: book, row: byOrigin[book.spec.origin], episodes: episodes, room: room,
                               onOpenDetails: onOpenDetails, cell: cell, night: night)
                    .offset(x: CGFloat(book.x) * cell, y: -CGFloat(book.y) * cell)
                    // Inside the pile's own container: largest first (§11), whatever the drawing order.
                    .accessibilitySortPriority(-Double(books.firstIndex(of: book.spec) ?? books.count))
            }
        }
        .frame(width: layout.pileFrame.width, height: layout.pileFrame.height, alignment: .bottomLeading)
        .animation(SleepMotion.pile(reduceMotion: reduceMotion), value: books)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(pileAccessibilityLabel(sourceCount: rows.count))
        .accessibilitySortPriority(RoomA11yOrder.spines)
    }
}

/// One book as a control (Track Z §7.1): a click opens its source's queue — the folded "+N" opens Waiting instead
/// (Z-P20: it folds several sources). Hover lifts it one whole cell and tints its Waiting row through
/// `room.hoveredOrigin` (I5, I7). No book starts, cancels or schedules a cycle (R-Z9).
struct PileBookButton: View {
    let book: PlacedBook
    let row: StudyRow?
    let episodes: [EpisodeQueueItem]
    let room: RoomModel?
    let onOpenDetails: (DetailsSection) -> Void
    let cell: CGFloat
    var night = false

    @State private var hovering = false
    @State private var showPopover = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let lifted = hovering || room?.hoveredOrigin == book.spec.origin
        Button {
            if book.spec.isRemainder || row == nil { onOpenDetails(.waiting) } else { showPopover = true }
        } label: {
            art.contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { inside in
            hovering = inside
            room?.hover(origin: book.spec.origin, inside: inside)
        }
        .roomLinkCursor()
        .help(spineHelp(spec: book.spec, row: row))
        .accessibilityLabel(spineAccessibilityLabel(spec: book.spec, row: row))
        .popover(isPresented: $showPopover, arrowEdge: .trailing) {
            if let row {
                SpinePopover(row: row, episodes: episodes) {
                    showPopover = false
                    onOpenDetails(.waiting)
                }
            }
        }
        // A lift is one whole cell, on the lattice like every sprite; the lifted book draws over the one above it.
        .offset(y: lifted && !reduceMotion ? -cell : 0)
        .zIndex(lifted ? 1 : 0)
        .animation(SleepMotion.hover(reduceMotion: reduceMotion), value: lifted)
    }

    private var art: some View {
        let size = CGSize(width: CGFloat(book.width) * cell, height: CGFloat(book.rows) * cell)
        return ZStack(alignment: .bottomLeading) {
            if let image = BookArt.image(kind: book.kind, step: book.step, width: book.width, night: night) {
                Image(decorative: image, scale: 1)
                    .resizable()
                    .interpolation(.none)
                    .frame(width: size.width, height: size.height)
                    .id(night)
                    .transition(.opacity)
            } else {
                // The sheet failed to load (logged once by `SpriteSheets`): a plain block, still a control.
                Rectangle().fill(CicadaTheme.textTertiary)
            }
            if let plate = PileBooks.plate(for: book, cell: cell, uiScale: CicadaTheme.uiScale) {
                HStack(spacing: CicadaTheme.scaled(PileBooks.markGap)) {
                    if plate.showsMark { OriginMark(origin: book.spec.origin, size: CicadaTheme.scaled(PileBooks.markPoints)) }
                    Text(PileBooks.label(book.spec))
                        .font(CicadaTheme.font(size: 11, weight: .medium))
                        .monospacedDigit()
                        // Z-P19 — a theme token on the page ground, never a literal.
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                        .fixedSize()
                }
                .frame(width: CGFloat(plate.width) * cell, height: CGFloat(plate.height) * cell)
                .background(CicadaTheme.bgBase)
                .offset(x: CGFloat(plate.x - book.x) * cell, y: -CGFloat(plate.y - book.y) * cell)
            }
        }
        .frame(width: size.width, height: size.height, alignment: .bottomLeading)
        .animation(SleepMotion.weather(reduceMotion: reduceMotion), value: night)
    }
}
