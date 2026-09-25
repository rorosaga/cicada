import SwiftUI

/// Every in-page "no match" ends with this row (design §3.7): the same words,
/// searched everywhere — it opens the ⌘K palette prefilled.
struct SearchAllMemoryRow: View {
    let query: String
    @Environment(AppRouter.self) private var router

    var body: some View {
        Button { router.requestPalette(prefill: Self.trimmed(query)) } label: {
            Label(Self.title(query), systemImage: "magnifyingglass").font(CicadaTheme.captionFont)
        }
        .buttonStyle(.cicadaPlain)
        .foregroundStyle(CicadaTheme.accent)
        .help("Search all of memory (⌘K)")
    }

    static func trimmed(_ query: String) -> String { query.trimmingCharacters(in: .whitespacesAndNewlines) }
    static func title(_ query: String) -> String { "Search all of memory for “\(trimmed(query))” (⌘K)" }
}
