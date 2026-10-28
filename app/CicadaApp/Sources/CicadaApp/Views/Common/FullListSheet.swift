import SwiftUI

/// Ruling 48 (17), DR-81 — no stacked folds: a list that is too long to draw whole on its page shows its first few,
/// open, and "All N" opens the whole of it here — a sheet (DR-33's grammar for a panel that is not a page), its title
/// and one *Done*, the rows in one scroll. Esc closes it. Never a disclosure.
struct FullListSheet<Content: View>: View {
    let title: String
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
                VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) { content }
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
