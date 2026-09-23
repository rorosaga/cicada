import SwiftUI

/// The detail pane while a query is active (design §2.4): hits grouped by
/// section in sidebar order, each with its section glyph, the title with the
/// matched letters in semibold, a `Section › Row` breadcrumb, a live value
/// the window already knows, and a chevron. A stock `List(selection:)` keeps
/// AX-selectable rows for `macos-harness`; choosing one lands on it.
struct SettingsResultsView: View {
    let query: String
    let hits: [SettingsHit]
    let liveValue: (SettingsEntry) -> String?
    let open: (SettingsEntry) -> Void
    @State private var selection: SettingsRowID?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                Text(Copy.resultsFor(query))
                    .font(CicadaTheme.displayFont(size: 24))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                Text(Copy.settingsCount(hits.count))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.top, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingSM)

            List(selection: $selection) {
                ForEach(SettingsIndex.grouped(hits), id: \.section) { group in
                    Section(group.section.title) {
                        ForEach(group.hits) { hit in
                            HStack(spacing: CicadaTheme.spacingMD) {
                                Image(systemName: hit.entry.section.icon)
                                    .foregroundStyle(CicadaTheme.textSecondary)
                                    .frame(width: CicadaTheme.scaled(18))
                                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                                    Text(SettingsIndex.attributedTitle(hit.entry.title, ranges: hit.titleRanges))
                                        .font(CicadaTheme.bodyFont)
                                    Text("\(hit.entry.section.title) › \(hit.entry.title)")
                                        .font(CicadaTheme.captionFont)
                                        .foregroundStyle(CicadaTheme.textTertiary)
                                }
                                Spacer(minLength: CicadaTheme.spacingSM)
                                if let value = liveValue(hit.entry) {
                                    Text(value)
                                        .font(CicadaTheme.captionFont)
                                        .foregroundStyle(CicadaTheme.textSecondary)
                                }
                                Image(systemName: "chevron.right")
                                    .font(CicadaTheme.captionFont)
                                    .foregroundStyle(CicadaTheme.textTertiary)
                            }
                            .contentShape(Rectangle())
                            // A click opens. Opening on every `selection` change
                            // instead would fire on the first ↓ and leave the list,
                            // so the arrows could never browse (design §2.4).
                            .onTapGesture { open(hit.entry) }
                            .accessibilityAction(.default) { open(hit.entry) }
                            .tag(hit.entry.id)
                            .accessibilityIdentifier("settings.result.\(hit.entry.id.rawValue)")
                        }
                    }
                }
            }
            // Tab into the list, ↑/↓ move the native selection, Return opens it.
            .onKeyPress(.return) {
                guard let id = selection, let hit = hits.first(where: { $0.entry.id == id }) else { return .ignored }
                open(hit.entry)
                return .handled
            }
        }
    }
}
