import AppKit
import SwiftUI

// MARK: - A line with chips and a source cluster (owner 2026-11-23, DESIGN_RULES §9)
//
// A `Text` cannot hold a view, so a line that carries a link chip or the cluster that ends a cited passage is laid out
// by `InlineFlowLayout`: its words, chips and cluster wrap like a paragraph, every piece on the line's one baseline, a
// piece that touched the one before it (a full stop after a chip) never split from it, and the cluster glued to the
// last word so it can never sit alone on a line. The price is the text's selection: each word is its own `Text`, so a
// line drawn this way is copied with its right-click menu's Copy, not by dragging. A line with no chip and no cluster
// never comes here: it stays one selectable `Text`. Only the rows on screen are built (`WikiPageView`'s lazy stack).

/// Wraps its subviews left to right, aligned on their first text baseline. `space` separates pieces that were apart in
/// the text; a piece marked `glued` follows its predecessor with `InlineFlowLayout.Lead` points and no break.
struct InlineFlowLayout: Layout {
    var space: CGFloat
    var lineSpacing: CGFloat

    struct Glued: LayoutValueKey { static let defaultValue = false }
    /// The gap before a glued piece (the cluster's breathing room after the last word); a touching word has none.
    struct Lead: LayoutValueKey { static let defaultValue: CGFloat = 0 }

    struct Entry {
        let index: Int
        var x: CGFloat
        let size: CGSize
        let ascent: CGFloat
    }

    struct Line {
        var entries: [Entry] = []
        var width: CGFloat = 0
        var ascent: CGFloat = 0
        var descent: CGFloat = 0
        var height: CGFloat { ascent + descent }
    }

    /// The text's own word space at the body size, so a flowed line reads like a plain one.
    static func spaceWidth(size: CGFloat) -> CGFloat {
        (" " as NSString).size(withAttributes: [.font: NSFont.systemFont(ofSize: size)]).width
    }

    /// One piece as the line breaker sees it: how big it is, where its baseline is, and whether it is glued to the one
    /// before it (with `lead` points between them).
    struct Measure: Equatable {
        var size: CGSize
        var ascent: CGFloat
        var glued = false
        var lead: CGFloat = 0
    }

    /// The line breaking, pure: greedy, a piece and everything glued after it placed whole or not at all, so a
    /// full stop never starts a line and the source cluster is never alone on one. Everywhere else a line may break, as
    /// plain text does. A glued run wider than the whole line is broken between its pieces, so only a single piece wider
    /// than the line ever overflows it.
    static func arrange(_ items: [Measure], width: CGFloat, space: CGFloat) -> [Line] {
        var lines: [Line] = []
        var current = Line()

        /// Places `run` (indices of pieces that must stay together) on the current line, or on a new one.
        func place(_ run: Range<Int>) {
            var entries: [Entry] = []
            var runWidth: CGFloat = 0
            for index in run {
                let lead = entries.isEmpty ? 0 : items[index].lead
                entries.append(Entry(index: index, x: runWidth + lead, size: items[index].size,
                                     ascent: items[index].ascent))
                runWidth += lead + items[index].size.width
            }
            let gap = current.entries.isEmpty ? 0 : space
            if !current.entries.isEmpty, width.isFinite, current.width + gap + runWidth > width {
                lines.append(current)
                current = Line()
            }
            let start = current.entries.isEmpty ? 0 : current.width + space
            for var entry in entries {
                entry.x += start
                current.entries.append(entry)
                current.ascent = max(current.ascent, entry.ascent)
                current.descent = max(current.descent, entry.size.height - entry.ascent)
            }
            current.width = start + runWidth
        }

        var index = 0
        while index < items.count {
            var end = index + 1
            var runWidth = items[index].size.width
            while end < items.count, items[end].glued {
                runWidth += items[end].lead + items[end].size.width
                end += 1
            }
            if width.isFinite, end - index > 1, runWidth > width {
                var from = index
                while from < end {
                    var to = from + 1
                    var w = items[from].size.width
                    while to < end, w + items[to].lead + items[to].size.width <= width {
                        w += items[to].lead + items[to].size.width
                        to += 1
                    }
                    place(from..<to)
                    from = to
                }
            } else {
                place(index..<end)
            }
            index = end
        }
        if !current.entries.isEmpty { lines.append(current) }
        return lines
    }

    func lines(in width: CGFloat, _ subviews: Subviews) -> [Line] {
        let proposal = ProposedViewSize(width: width.isFinite ? width : nil, height: nil)
        let items = subviews.map { subview -> Measure in
            let dims = subview.dimensions(in: proposal)
            return Measure(size: CGSize(width: dims.width, height: dims.height), ascent: dims[.firstTextBaseline],
                           glued: subview[Glued.self], lead: subview[Lead.self])
        }
        return Self.arrange(items, width: width, space: space)
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        let arranged = lines(in: width, subviews)
        let height = arranged.reduce(0) { $0 + $1.height } + lineSpacing * CGFloat(max(arranged.count - 1, 0))
        // The proposed width is the answer: `placeSubviews` then breaks lines at the same measure.
        return CGSize(width: proposal.width ?? (arranged.map(\.width).max() ?? 0), height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var top = bounds.minY
        for line in lines(in: bounds.width, subviews) {
            for entry in line.entries {
                let y = top + line.ascent - entry.ascent
                subviews[entry.index].place(at: CGPoint(x: bounds.minX + entry.x, y: y), anchor: .topLeading,
                                            proposal: ProposedViewSize(width: entry.size.width, height: entry.size.height))
            }
            top += line.height + lineSpacing
        }
    }
}

/// One line of an entity page drawn with its chips and its cluster. `font`, `ink` and `italic` are the row's own, so a
/// quote or a list item keeps its face; a chip wears the body face whatever the row is (`PageLinkChip`).
struct PageInlineFlow: View {
    let pieces: [PageInlinePiece]
    var font: Font = CicadaTheme.bodyFont
    var ink: Color = CicadaTheme.textPrimary
    var italic = false
    /// The page the line is on: its icon route serves a linked site's mark (`LinkFactsCache`), its popover reads its sources.
    let entityId: String?
    /// The quiet link under the pointer, so every word of one link lights together.
    @State private var hoveredGroup: Int?

    var body: some View {
        InlineFlowLayout(space: InlineFlowLayout.spaceWidth(size: CicadaTheme.scaled(14)),
                         lineSpacing: CicadaTheme.scaled(2)) {
            ForEach(pieces) { piece in
                view(piece)
                    .layoutValue(key: InlineFlowLayout.Glued.self, value: piece.glued)
                    .layoutValue(key: InlineFlowLayout.Lead.self, value: isCluster(piece) ? CicadaTheme.scaled(5) : 0)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(PageInline.plainText(pieces))
        .contextMenu {
            Button(Copy.Pages.copyLine) { AppPasteboard.copy(PageInline.plainText(pieces)) }
        }
    }

    private func isCluster(_ piece: PageInlinePiece) -> Bool {
        if case .cluster = piece.token { return true }
        return false
    }

    @ViewBuilder
    private func view(_ piece: PageInlinePiece) -> some View {
        switch piece.token {
        case .word(let words):
            Text(words)
                .font(font)
                .foregroundStyle(ink)
                .italic(italic)
                .fixedSize()
                .accessibilityHidden(true)   // the line's label reads them once
        case .entity(let target, let url):
            PageLinkChip(face: .page(target), url: url, entityId: entityId)
        case .external(let url, let label):
            PageLinkChip(face: .web(label: label), url: url, entityId: entityId)
        case .quiet(let word):
            PageQuietWordView(word: word, font: font, ink: ink, italic: italic, hovering: hoveredGroup == word.group) {
                if $0 { hoveredGroup = word.group } else if hoveredGroup == word.group { hoveredGroup = nil }
            }
        case .cluster(let model, let keys):
            if let entityId { SourceCluster(model: model, keys: keys, entityId: entityId) }
        }
    }
}

/// One word of a quiet link: the page's name (or the words as written) in body ink — no picture, no fill, no underline,
/// no accent — and on hover or keyboard focus a soft fill behind the whole link. The same click as the chip's: it opens
/// the page, or for a ref that matched no single page asks which (G227). The words of a link are one control for
/// assistive tech: the first carries its label.
struct PageQuietWordView: View {
    let word: PageQuietWord
    let font: Font
    let ink: Color
    let italic: Bool
    let hovering: Bool
    let onHover: (Bool) -> Void

    @Environment(\.openURL) private var openURL
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @FocusState private var focused: Bool

    var body: some View {
        let shape = CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
        Button { openURL(word.url) } label: {
            Text(word.text)
                .font(font)
                .foregroundStyle(ink)
                .italic(italic)
                .fixedSize()
                .background {
                    // Reaches 2 pt past the word each side, so the fills of a name's words meet across the space.
                    shape.fill(hovering || focused ? CicadaTheme.bgHover : .clear)
                        .padding(.horizontal, -CicadaTheme.scaled(2))
                        .padding(.vertical, -CicadaTheme.scaled(1))
                }
                .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover(perform: onHover)
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .focusable(word.first)
        .focused($focused)
        .focusEffectDisabled()
        .onKeyPress(.return) {
            openURL(word.url)
            return .handled
        }
        .help(word.first ? Copy.Pages.openPage(word.label) : "")
        .accessibilityHidden(!word.first)
        .accessibilityLabel(word.label)
        .accessibilityAddTraits(.isLink)
    }
}
