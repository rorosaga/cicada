import SwiftUI

/// §5.3 for the browse pages — Clusters, the Feed, Sources (R-DL6): which row is open, pure. The Inbox keeps
/// `InboxColumns`: answering, Undo and kind filters are its own, and DS-2's reducer ships untouched.
///
/// A row that leaves the DATA closes the detail — a browse page has no next answer to hand the column to, and a card
/// that silently became another entity would be a lie. A row the find field or a tab merely hides stays open:
/// narrowing the list is not closing the card.
struct ListColumns<ID: Hashable>: Equatable {
    private(set) var openId: ID?

    enum Escape: Equatable { case closeReader, closeDetail, none }

    mutating func open(_ id: ID) { openId = id }
    mutating func close() { openId = nil }

    /// DR-68 — ↑/↓: the neighbour, clamped; from nothing (or from a row the list no longer shows), the first (↓) or
    /// the last (↑).
    func neighbour(_ delta: Int, in visible: [ID]) -> ID? {
        guard !visible.isEmpty else { return nil }
        guard let id = openId, let i = visible.firstIndex(of: id) else {
            return delta >= 0 ? visible.first : visible.last
        }
        return visible[min(max(i + delta, 0), visible.count - 1)]
    }

    mutating func reconcile(present: Set<ID>) {
        if let id = openId, !present.contains(id) { openId = nil }
    }

    /// DR-28 — Esc closes the rightmost open thing.
    func escape(readerOpen: Bool) -> Escape {
        readerOpen ? .closeReader : (openId == nil ? .none : .closeDetail)
    }
}

/// Where the keys sit on a progressive page — DR-68's Tab order: list → detail → Reader.
enum ListFocus: Hashable { case list, detail, reader }

/// §5.3 — the list column's insets: 30 + a row's own 10 = the 40 gutter with nothing open; the mock's `0 8 24 12`
/// beside a detail. The Inbox's list spells the same numbers.
enum ListInsets {
    static func of(_ style: ColumnPlan.ListStyle) -> EdgeInsets {
        switch style {
        case .wide:
            EdgeInsets(top: 0, leading: CicadaTheme.scaled(30), bottom: CicadaTheme.scaled(72),
                       trailing: CicadaTheme.scaled(30))
        case .triage, .titles, .hidden:
            EdgeInsets(top: 0, leading: CicadaTheme.scaled(12), bottom: CicadaTheme.scaled(24),
                       trailing: CicadaTheme.scaled(8))
        }
    }
}

/// DR-34 / DR-48 / §5.5 — a list row's one height per role and its one fill: `bgHover` on hover, `bgSelected` when
/// open. Never a lift, a scale, a shadow or the accent (`SelectionTintLintTests`).
struct ListRowSurface: ViewModifier {
    let height: CGFloat
    let selected: Bool
    @State private var hovering = false

    /// §5.5 — 36 one-line, 56 two-line, 36 titles-only. The Feed's rows are two lines at rest (§10: "Rows are 56 pt").
    static func height(_ style: ColumnPlan.ListStyle, twoLineAtRest: Bool = false) -> CGFloat {
        switch style {
        case .wide: twoLineAtRest ? RowMetrics.twoLine : RowMetrics.oneLine
        case .triage: RowMetrics.twoLine
        case .titles, .hidden: RowMetrics.titleOnly
        }
    }

    func body(content: Content) -> some View {
        content
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(height), maxHeight: CicadaTheme.scaled(height),
                   alignment: .leading)
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(selected ? CicadaTheme.bgSelected : (hovering ? CicadaTheme.bgHover : Color.clear)))
            .contentShape(Rectangle())
            .onHover { hovering = $0 }
    }
}

extension View {
    func listRowSurface(height: CGFloat, selected: Bool) -> some View {
        modifier(ListRowSurface(height: height, selected: selected))
    }

    /// DR-68 (R-DL8) — a browse list's keys: ↑/↓ open the neighbour in place, ⏎ steps into the detail (return false
    /// when nothing is open), Esc closes the rightmost column. The caller runs each in `Instant.run` (DR-60).
    func listKeys(move: @escaping (Int) -> Void, enter: @escaping () -> Bool,
                  escape: @escaping () -> Void) -> some View {
        focusable()
            .focusEffectDisabled()
            .onMoveCommand { direction in
                switch direction {
                case .up: move(-1)
                case .down: move(1)
                default: break
                }
            }
            .onKeyPress(.return) { enter() ? .handled : .ignored }
            .onExitCommand { escape() }
    }
}

/// DR-43 — a first fetch says so in words over a still skeleton (no shimmer), as the Inbox's does.
struct ListSkeleton: View {
    let message: String
    private static let bars: [CGFloat] = [0.38, 0.52, 0.31, 0.46, 0.58, 0.35]

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(24)) {
            Text(message)
                .font(CicadaTheme.detailBodyFont)
                .foregroundStyle(CicadaTheme.textTertiary)
            ForEach(Array(Self.bars.enumerated()), id: \.offset) { _, fraction in
                CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                    .fill(CicadaTheme.bgSelected)
                    .frame(width: CicadaTheme.scaled(520 * fraction), height: CicadaTheme.scaled(12))
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(message)
    }
}

/// DR-43 / DR-40 — a failed first fetch: what failed, why, and a neutral Retry in a `radiusLarge` card.
struct ListErrorCard: View {
    let title: String
    let message: String
    let retry: () -> Void

    var body: some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            Text(title)
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)
            Text(message)
                .font(CicadaTheme.detailBodyFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            NeutralButton(title: Copy.Inbox.retry, action: retry)
        }
        .padding(CicadaTheme.spacingXL)
        .frame(maxWidth: CicadaTheme.scaled(420))
        .background(CicadaTheme.shape(CicadaTheme.radiusLarge).fill(CicadaTheme.bgFocus))
        .ringed(in: CicadaTheme.shape(CicadaTheme.radiusLarge))
        .frame(maxWidth: .infinity)
        .padding(.top, CicadaTheme.scaled(80))
    }
}
