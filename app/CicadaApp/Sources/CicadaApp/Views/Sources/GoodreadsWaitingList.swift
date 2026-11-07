import SwiftUI

/// ROR-128 — the books the person's own agent read on their Goodreads shelves wait here until the person picks, the
/// same pick list the file import uses (`BookChoiceList`, #666): all ticked, *Add all* / *Add N*, *Select none*,
/// *Leave out*. Nothing is in memory before that. DR-5 (one primary: the add), DR-38 (said once), DR-59 (one line).
struct GoodreadsWaitingList: View {
    @Environment(Store.self) private var store
    @Environment(ReadingAgentModel.self) private var reading
    @State private var items: [GoodreadsWaiting.Item] = []
    @State private var busy = false
    @State private var line: BooksRowText.Line?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if !items.isEmpty {
                Text(Copy.booksChoosing(items.count)).font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                BookChoiceList(items: items.map { BookChoiceItem(id: $0.id, title: $0.title, author: $0.author) },
                               busy: busy, onLeaveOut: { _ in Task { await choose([]) } }) { ids in
                    Task { await choose(Array(ids)) }
                }
            }
            if let line {
                Text(line.text).font(CicadaTheme.metaFont)
                    .foregroundStyle(line.isProblem ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            }
        }
        // Asked when the page is drawn and again when a read lands (the books arrive while the page is open).
        .task(id: store.bank) { await load() }
        .task(id: reading.settings?.saved?.lists["goodreads"]?.lastReadAt) { await load() }
    }

    private func load() async {
        items = (try? await APIClient.shared.fetchGoodreadsWaiting().items) ?? []
    }

    private func choose(_ ids: [String]) async {
        busy = true
        defer { busy = false }
        do {
            let result = try await APIClient.shared.chooseGoodreadsWaiting(ids: ids)
            line = ids.isEmpty ? nil : .init(text: Copy.goodreadsImported(result.books))
            items = []
            await store.refresh([.channels, .sources, .sourcesOverview, .status])
        } catch {
            line = .init(text: Copy.goodreadsFailed, isProblem: true)
        }
    }
}
