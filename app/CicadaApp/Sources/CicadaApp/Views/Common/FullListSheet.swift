import SwiftUI

/// Ruling 48 (17), DR-81 — no stacked folds: a list that is too long to draw whole on its page shows its first few,
/// open, and "All N" opens the whole of it here — a sheet (DR-33's grammar for a panel that is not a page), its title
/// and one *Done*, the rows in one scroll. Esc closes it. Never a disclosure.
///
/// The rows are lazy (inbox freeze, owner 2026-10-29): the sheet opens at once at a few thousand rows and builds the
/// rest as they scroll in. Pass the rows as a `ForEach` straight in `content` — rows wrapped in a stack of their own are
/// one child of the lazy stack, built whole (`FullListSheetBenchTests` holds the budget).
struct FullListSheet<Content: View>: View {
    let title: String
    /// Between rows: the list's own gap, as its capped form on the page draws it.
    var spacing: CGFloat = CicadaTheme.spacingMD
    @ViewBuilder let content: Content

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(title)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: CicadaTheme.spacingSM)
                NeutralButton(title: Copy.FullList.done, size: .compact) { dismiss() }
            }
            .padding(CicadaTheme.spacingLG)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: spacing) { content }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, CicadaTheme.spacingLG)
                    .padding(.bottom, CicadaTheme.spacingLG)
            }
        }
        .frame(minWidth: CicadaTheme.scaled(560), idealWidth: CicadaTheme.scaled(640),
               minHeight: CicadaTheme.scaled(420), idealHeight: CicadaTheme.scaled(560))
        .background(CicadaTheme.bgBase)
        .onExitCommand { dismiss() }
    }
}

extension Copy {
    enum FullList {
        static let done = "Done"
        static func all(_ n: Int) -> String { "All \(UsageFormat.count(n))" }
        static let allHelp = "Show the whole list"
    }
}
