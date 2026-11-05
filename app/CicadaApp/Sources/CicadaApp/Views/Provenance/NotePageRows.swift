import AppKit
import SwiftUI

/// ROR-15, G161 — an Apple Note on a quiet page, read-only (DR-18: SF, every word through the quote face; DR-31: inside
/// the Reader). One row per line, each `.id` the `ReaderBlock` landing and the rotors address. Spans are `CitedSpan.marks`,
/// the one standard: a formatted note and the plain view wash the same words the same way.
struct NotePageRow: Hashable, Identifiable {
    let block: NoteDocument.Block
    let reader: ReaderBlock
    var id: ReaderBlock.Key { reader.id }
}

extension NoteDocument {
    /// The page's rows and the blocks landing reads, with the washes each span gives each line. A note whose first line
    /// is the header's title leaves it to the header, unless a span lies on it.
    func rows(doc: EpisodeText, turn: Int, focus: Range<Int>?, focusStyle: ReaderWash.Style,
              others: [Range<Int>]) -> [NotePageRow] {
        var rows: [NotePageRow] = []
        var at = 0
        for (n, block) in blocks.enumerated() {
            var washes: [ReaderWash] = []
            if let focus { washes += ranges(of: focus, in: block).map { ReaderWash(range: $0, style: focusStyle) } }
            for other in others where other != focus {
                washes += ranges(of: other, in: block).map { ReaderWash(range: $0, style: .other) }
            }
            washes.sort { $0.range.lowerBound < $1.range.lowerBound }
            at = block.map.first { $0 >= 0 } ?? at
            if block.kind == .title, washes.isEmpty, block.text == doc.title { continue }
            let reader = ReaderBlock(index: turn, chunk: n, role: "user", speaker: "", mark: nil, time: nil, text: block.text,
                                     contentStart: at, washes: washes, showsTurnNumber: false)
            rows.append(NotePageRow(block: block, reader: reader))
        }
        return rows
    }
}

enum NoteText {
    /// A stretch of a line as one string: the note's own styles, then the span's marks over them.
    static func attributed(_ block: NoteDocument.Block, range: Range<Int>, washes: [ReaderWash],
                           reveal: Double) -> AttributedString {
        var out = AttributedString()
        func rank(_ s: ReaderWash.Style) -> Int { s == .other ? 1 : 0 }
        let ordered = washes.sorted { ($0.range.lowerBound, rank($0.style)) < ($1.range.lowerBound, rank($1.style)) }
        for run in block.runs {
            let lo = max(run.range.lowerBound, range.lowerBound), hi = min(run.range.upperBound, range.upperBound)
            guard hi > lo else { continue }
            var cursor = lo
            func piece(_ end: Int, _ mark: CitedSpan.Mark) {
                guard end > cursor else { return }
                var view = String.UnicodeScalarView()
                view.append(contentsOf: block.scalars[cursor..<end])
                var words = AttributedString(String(view))
                words.mergeAttributes(attributes(run))
                words.mergeAttributes(CitedSpan.marks(mark, reveal: reveal))
                out.append(words)
                cursor = end
            }
            for wash in ordered where wash.range.upperBound > cursor && wash.range.lowerBound < hi {
                guard wash.range.lowerBound <= cursor || wash.range.lowerBound < hi else { continue }
                piece(min(max(wash.range.lowerBound, cursor), hi), .plain)
                let mark: CitedSpan.Mark = switch wash.style {
                case .focus: .current
                case .other: .other
                case .mention: .mention
                }
                piece(min(wash.range.upperBound, hi), mark)
            }
            piece(hi, .plain)
        }
        return out
    }

    private static func attributes(_ run: NoteDocument.Run) -> AttributeContainer {
        var c = AttributeContainer()
        var intent = InlinePresentationIntent()
        if run.style.contains(.bold) { intent.insert(.stronglyEmphasized) }
        if run.style.contains(.italic) { intent.insert(.emphasized) }
        if run.style.contains(.mono) { intent.insert(.code) }
        if !intent.isEmpty { c.inlinePresentationIntent = intent }
        if run.style.contains(.underline) { c.swiftUI.underlineStyle = .single }
        if run.style.contains(.strike) { c.swiftUI.strikethroughStyle = .single }
        if let link = run.link {
            c.link = link
            c.swiftUI.underlineStyle = .single
        }
        return c
    }

    /// A link is data until the person clicks it: only a plain http(s) one opens, checked again here (`ItemPlaceOpen`).
    static let openLink = OpenURLAction { url in
        guard let safe = ItemPlaceOpen.webURL(url.absoluteString) else { return .discarded }
        NSWorkspace.shared.open(safe)
        return .handled
    }

    static func markerWord(_ marker: NoteDocument.Marker) -> String {
        switch marker {
        case .bullet: "•"
        case .dash: "–"
        case let .number(n): "\(n)."
        case .check: ""
        }
    }
}

/// The rows, flattened into the Reader's lazy stack like `ReaderTurnRows`.
struct NotePageRows: View {
    let rows: [NotePageRow]
    let revealed: Bool

    var body: some View {
        ForEach(rows) { row in
            NoteLine(row: row, reveal: revealed ? 1 : 0)
                .padding(.top, CicadaTheme.scaled(Self.gap(row, first: row.id == rows.first?.id)))
                .id(row.id)
        }
        .environment(\.openURL, NoteText.openLink)
        // DR-5: the accent's six uses stay six. A link in a note reads as ink, marked by its underline.
        .tint(CicadaTheme.textPrimary)
    }

    private static func gap(_ row: NotePageRow, first: Bool) -> CGFloat {
        if first { return 0 }
        switch row.block.kind {
        case .title: return 0
        case .heading(1), .heading(2): return 20
        case .heading: return 14
        case .table: return 10
        case .item, .itemLine: return 3
        case .blank: return 0
        default: return 6
        }
    }
}

private struct NoteLine: View {
    let row: NotePageRow
    let reveal: Double

    private var block: NoteDocument.Block { row.block }
    private var washes: [ReaderWash] { row.reader.washes }

    var body: some View {
        switch block.kind {
        case .blank:
            Color.clear.frame(height: CicadaTheme.scaled(10))
        case .title:
            line(font: CicadaTheme.titleFont, spacing: CicadaTheme.scaled(3))
        case .heading(1), .heading(2):
            line(font: CicadaTheme.headingFont, spacing: CicadaTheme.scaled(3))
        case .heading:
            line(font: CicadaTheme.quoteFont(size: 15).weight(.semibold))
        case .paragraph:
            line()
        case .quote:
            line().quoteBlock()
        case .code:
            line(font: CicadaTheme.quoteFont(size: 13).monospaced())
        case let .item(marker, depth):
            HStack(alignment: .firstTextBaseline, spacing: 0) {
                markerView(marker)
                    .frame(width: CicadaTheme.scaled(Self.gutter), alignment: .leading)
                line()
            }
            .padding(.leading, CicadaTheme.scaled(Self.gutter) * CGFloat(min(depth, 8)))
        case let .itemLine(depth):
            line().padding(.leading, CicadaTheme.scaled(Self.gutter) * CGFloat(min(depth, 8) + 1))
        case let .table(grid):
            NoteTable(block: block, grid: grid, washes: washes, reveal: reveal)
        }
    }

    private static let gutter: CGFloat = 20

    private func line(font: Font = CicadaTheme.quoteFont, spacing: CGFloat = CicadaTheme.quoteLineSpacing) -> some View {
        Text(NoteText.attributed(block, range: 0..<block.scalars.count, washes: washes, reveal: reveal))
            .font(font)
            .lineSpacing(spacing)
            .foregroundStyle(CicadaTheme.textPrimary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .textSelection(.enabled)
    }

    @ViewBuilder private func markerView(_ marker: NoteDocument.Marker) -> some View {
        if case let .check(done) = marker {
            Image(systemName: done ? "checkmark.circle.fill" : "circle")
                .font(CicadaTheme.quoteFont(size: 13))
                .foregroundStyle(done ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
                .accessibilityLabel(done ? Copy.Provenance.noteChecked : Copy.Provenance.noteUnchecked)
        } else {
            Text(NoteText.markerWord(marker))
                .font(CicadaTheme.quoteFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .accessibilityHidden(true)
        }
    }
}

/// A hairline grid with no fill and no shadow, as a note's own table is ruled (DR-9, DR-10).
private struct NoteTable: View {
    let block: NoteDocument.Block
    let grid: [[Range<Int>]]
    let washes: [ReaderWash]
    let reveal: Double

    var body: some View {
        let columns = grid.map(\.count).max() ?? 0
        Grid(alignment: .topLeading, horizontalSpacing: 0, verticalSpacing: 0) {
            ForEach(grid.indices, id: \.self) { r in
                GridRow {
                    ForEach(0..<columns, id: \.self) { c in
                        cell(c < grid[r].count ? grid[r][c] : 0..<0)
                    }
                }
            }
        }
        .overlay(Rectangle().strokeBorder(CicadaTheme.borderLight, lineWidth: 1))
    }

    private func cell(_ range: Range<Int>) -> some View {
        Text(NoteText.attributed(block, range: range, washes: washes, reveal: reveal))
            .font(CicadaTheme.quoteFont(size: 14))
            .foregroundStyle(CicadaTheme.textPrimary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .textSelection(.enabled)
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.vertical, CicadaTheme.spacingXS)
            .overlay(Rectangle().strokeBorder(CicadaTheme.borderLight.opacity(0.7), lineWidth: 0.5))
    }
}
