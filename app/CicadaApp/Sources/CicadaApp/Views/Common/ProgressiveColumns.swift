import SwiftUI

/// One arrangement of the progressive columns (DESIGN_RULES §5.3), in points that sum to exactly
/// the content width — so nothing is ever pushed off-window (DR-31). The `.inspector` the Reader
/// used to live in could not promise that, and clipped the Reader's text (R-DI6).
struct ColumnPlan: Equatable {
    enum ListStyle: Equatable {
        /// STATE 0 — one-line rows at full width, or beside a Reader opened elsewhere (R-DI8).
        case wide
        /// STATE 1 — the triage column: two-line rows.
        case triage
        /// STATE 2 — titles only, so the question keeps its 440.
        case titles
        /// DR-27 — the question and the Reader could not both keep their floor with it on screen.
        case hidden
    }

    var list: CGFloat
    var detail: CGFloat
    var trailing: CGFloat
    var listStyle: ListStyle
    /// 40 with at most two columns, 24 once the Reader sits beside the question (§5.3 STATE 2).
    var gutter: CGFloat
    /// The focus card's padding: `spacingCard` (28), 24 in STATE 2.
    var cardPadding: CGFloat

    var listHidden: Bool { listStyle == .hidden }
}

/// §5.3's widths, pure (DR-27, DR-36, DR-70; R-DI7). Every number is at uiScale 1 — "units" — and
/// `plan` works in units and hands back points, so ⌘+ narrows the columns exactly as it grows the
/// type (G130): at 1.4× a 1440 window lays out like a ~1030 one. The table's widths are keyed on
/// the WINDOW (the rail and the labelled sidebar share them), the floors on the space left.
enum ColumnLayout {
    static let minQuestion: CGFloat = 440       // DR-27
    static let minReader: CGFloat = 360         // DR-27
    static let titlesList: CGFloat = 260        // §5.3 STATE 2
    static let questionMaxWidth: CGFloat = 720  // DR-36 — the focus card
    static let textMaxWidth: CGFloat = 760      // DR-36 — a row's text
    static let gutterWide: CGFloat = 40
    static let gutterNarrow: CGFloat = 24
    static let cardPaddingWide: CGFloat = 28    // `spacingCard`
    static let cardPaddingNarrow: CGFloat = 24

    /// 280 at a 1200 window, 328 at 1440, straight between, clamped (§5.3's table).
    static func triageListWidth(window: CGFloat) -> CGFloat {
        min(max(280 + (window - 1200) * 0.2, 280), 328)
    }

    /// 360 at a 1200 window, 420 at 1440, straight between, clamped.
    static func readerWidth(window: CGFloat) -> CGFloat {
        min(max(360 + (window - 1200) * 0.25, 360), 420)
    }

    /// R-DI7 (§9) — neither floor fits: the question and the Reader share the width 440 : 360.
    private static func overflowReader(_ available: CGFloat) -> CGFloat {
        available * minReader / (minQuestion + minReader)
    }

    static func plan(contentWidth: CGFloat, navWidth: CGFloat, scale: CGFloat,
                     hasList: Bool = true, hasDetail: Bool, hasTrailing: Bool) -> ColumnPlan {
        let s = max(scale, 0.1)
        let content = max(contentWidth, 0)
        let window = (content + max(navWidth, 0)) / s
        let available = content / s
        // Nearest, not down: 280 × 1.4 is 391.99999… in binary floating point. The flexible column
        // takes the remainder, so rounding a fixed one never breaks the exact sum.
        func points(_ units: CGFloat) -> CGFloat { (units * s).rounded() }
        func scaled(_ units: CGFloat) -> CGFloat { (units * s * 10).rounded() / 10 }

        var listUnits: CGFloat = 0
        var readerUnits: CGFloat = hasTrailing ? min(readerWidth(window: window), available) : 0
        var style = ColumnPlan.ListStyle.hidden
        switch (hasList, hasDetail) {
        case (true, false):
            if available - readerUnits >= titlesList || !hasTrailing {
                style = .wide
            } else {
                readerUnits = available
            }
        case (true, true) where !hasTrailing:
            let triage = triageListWidth(window: window)
            if available - triage >= minQuestion {
                listUnits = triage
                style = .triage
            }
        case (true, true):
            if available - titlesList - readerUnits >= minQuestion {
                listUnits = titlesList
                style = .titles
            } else if available - readerUnits < minQuestion {
                readerUnits = overflowReader(available)
            }
        case (false, true):
            if hasTrailing, available - readerUnits < minQuestion { readerUnits = overflowReader(available) }
        case (false, false):
            break
        }

        let reader = hasTrailing ? points(readerUnits) : 0
        let list: CGFloat
        let detail: CGFloat
        if hasDetail {
            list = style == .hidden ? 0 : points(listUnits)
            detail = max(content - list - reader, 0)
        } else {
            list = style == .hidden ? 0 : max(content - reader, 0)
            detail = 0
        }
        let narrow = hasDetail && hasTrailing
        return ColumnPlan(
            list: list, detail: detail, trailing: hasTrailing ? max(content - list - detail, 0) : 0,
            listStyle: hasList ? style : .hidden,
            gutter: scaled(narrow ? gutterNarrow : gutterWide),
            cardPadding: scaled(narrow ? cardPaddingNarrow : cardPaddingWide))
    }
}

/// §5.3 — the list alone; the list and its detail; the list, the detail and the source. One
/// container: the Inbox adopts it (DS-2), and Clusters, the Feed, Sources and Projects next (§10).
///
/// The header (the eyebrow row, DR-25) spans the list and the detail; the trailing column runs the
/// full height beside both, as the approved mock draws the Reader. The widths come from
/// `ColumnLayout.plan` alone and the whole arrangement is clipped to the container, so a child with
/// a rigid minimum can never widen the window (R-DI6). Animation belongs to the caller: a pointer
/// path wraps its change in `withAnimation`, a keyboard path in `Instant.run` (DR-60).
struct ProgressiveColumns<Header: View, List: View, Detail: View, Trailing: View>: View {
    let hasDetail: Bool
    let hasTrailing: Bool
    /// The shell's navigation width, scaled (`ShellMetrics.navWidth(labelled:)`) — the table's widths
    /// are keyed on the window, which is this container plus the rail or the sidebar.
    let navWidth: CGFloat
    @ViewBuilder var header: (ColumnPlan) -> Header
    @ViewBuilder var list: (ColumnPlan) -> List
    @ViewBuilder var detail: (ColumnPlan) -> Detail
    @ViewBuilder var trailing: (ColumnPlan) -> Trailing

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        GeometryReader { geo in
            let plan = ColumnLayout.plan(contentWidth: geo.size.width, navWidth: navWidth,
                                         scale: CGFloat(CicadaTheme.uiScale),
                                         hasDetail: hasDetail, hasTrailing: hasTrailing)
            HStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 0) {
                    header(plan)
                    HStack(spacing: 0) {
                        if !plan.listHidden {
                            list(plan).frame(width: plan.list).frame(maxHeight: .infinity)
                        }
                        if hasDetail {
                            detail(plan)
                                .frame(width: plan.detail)
                                .frame(maxHeight: .infinity)
                                .transition(.opacity)
                        }
                    }
                }
                .frame(width: plan.list + plan.detail)
                if hasTrailing {
                    trailing(plan)
                        .frame(width: plan.trailing)
                        .frame(maxHeight: .infinity)
                        .transition(CicadaMotion.readerTransition(reduceMotion: reduceMotion))
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .topLeading)
            .clipped()
        }
        // DR-61 — the trailing column opens on the drawer curve and closes faster, whoever opened it
        // (a chip, "Show in conversation", the palette). Esc closes it inside `Instant.run`, whose
        // transaction disables this animation (DR-60).
        .animation(hasTrailing ? CicadaMotion.readerIn(reduceMotion: reduceMotion)
                               : CicadaMotion.readerOut(reduceMotion: reduceMotion), value: hasTrailing)
    }
}

/// DR-34 / §5.5 — each row role has one height; no row sets its own vertical padding.
enum RowMetrics {
    static let oneLine: CGFloat = 36
    static let twoLine: CGFloat = 56
    static let titleOnly: CGFloat = 36
    static let option: CGFloat = 48
    static let twoLineGap: CGFloat = 2
    static let optionGap: CGFloat = 4
    static let menuItem: CGFloat = 30   // a menu's item: the D-Sleep mock's engine rows (DR-34)
}
