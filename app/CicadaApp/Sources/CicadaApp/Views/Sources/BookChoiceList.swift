import SwiftUI

/// G233 — several books could go into memory: the person confirms all or picks some, and nothing enters before that.
/// Everything starts ticked (confirm all is one click). DR-5 (one primary: the add), DR-38 (said once), DR-59 (one line a
/// book), DR-9 (a ring, not a border).
struct BookChoiceItem: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let author: String
}

struct BookChoiceList: View {
    let items: [BookChoiceItem]
    var busy = false
    /// Nil hides it: a source that can ask again (a file) has no "leave out".
    var onLeaveOut: ((Set<String>) -> Void)? = nil
    let onAdd: (Set<String>) -> Void

    @State private var ticked: Set<String> = []
    @State private var seeded = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingMD) {
                PrimaryActionButton(title: Copy.booksAddChosen(ticked.count, of: items.count)) { onAdd(ticked) }
                    .disabled(busy || ticked.isEmpty).fixedSize()
                TextButton(title: ticked.count == items.count ? Copy.booksSelectNone : Copy.booksSelectAll) {
                    ticked = ticked.count == items.count ? [] : Set(items.map(\.id))
                }
                if let onLeaveOut {
                    TextButton(title: Copy.booksLeaveOut) { onLeaveOut(ticked) }.disabled(busy)
                }
                Spacer(minLength: 0)
            }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(items) { item in
                        Toggle(isOn: Binding(get: { ticked.contains(item.id) },
                                             set: { on in if on { ticked.insert(item.id) } else { ticked.remove(item.id) } })) {
                            HStack(spacing: CicadaTheme.spacingSM) {
                                Text(item.title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                                    .lineLimit(1)
                                if !item.author.isEmpty {
                                    Text(item.author).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                                        .lineLimit(1)
                                }
                            }
                        }
                        .toggleStyle(.checkbox)
                        .frame(height: CicadaTheme.scaled(28), alignment: .leading)
                    }
                }
            }
            .frame(maxHeight: CicadaTheme.scaled(260))
        }
        .onAppear { if !seeded { ticked = Set(items.map(\.id)); seeded = true } }
        .onChange(of: items) { _, new in ticked = ticked.intersection(Set(new.map(\.id))).union(
            Set(new.map(\.id)).subtracting(Set(items.map(\.id)))) }
    }
}
