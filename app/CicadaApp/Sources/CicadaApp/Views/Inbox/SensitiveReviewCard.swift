import SwiftUI

/// G235 — the one review of what may be sensitive: a row per conversation, never a question per hit. Its title opens the
/// conversation in the Reader; the row says what kind and which engine read it, never the words. One group, ringed
/// (DR-37, DR-9); Remove is the quiet neutral button and Leave it the quieter text one (DR-40); a date, never an id
/// (DR-54). Answered row by row, optimistically, like *Confirm N links*.
struct SensitiveReviewCard: View {
    let item: InboxItem

    @Environment(Store.self) private var store
    @Environment(ProvenanceRouter.self) private var reader: ProvenanceRouter?
    @State private var answered: Set<String> = []
    @State private var showAll = false
    @State private var confirming: String?

    private static let firstRows = 3
    private var rows: [SensitiveRow] { (item.sensitiveRows ?? []).filter { !answered.contains($0.id) } }

    var body: some View {
        let rows = rows
        if !rows.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Text(item.questionText)
                    .font(CicadaTheme.metaMediumFont).foregroundStyle(CicadaTheme.textPrimary)
                Text(Copy.Sensitive.effect)
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
                ForEach(rows.prefix(Self.firstRows)) { rowView($0) }
                if rows.count > Self.firstRows {
                    InlineLink(title: Copy.Sensitive.allRows(rows.count)) { showAll = true }
                }
                if let replaced = item.replaced, replaced > 0 {
                    Text(Copy.Sensitive.replaced(replaced))
                        .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(CicadaTheme.spacingMD)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.bgFocus, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
            .sheet(isPresented: $showAll) {
                FullListSheet(title: item.questionText) {
                    ForEach(self.rows) { rowView($0) }
                }
                .environment(store)
            }
        }
    }

    private func rowView(_ row: SensitiveRow) -> some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Button {
                    reader?.open(ReaderTarget(episode: row.episode, knownTitle: row.title))
                } label: {
                    Text(row.title)
                        .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                }
                .buttonStyle(.cicadaPlain)
                Text(SensitiveRow.line(row))
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1).truncationMode(.tail)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            NeutralButton(title: Copy.Sensitive.remove, size: .compact) { confirming = row.id }
            TextButton(title: Copy.Sensitive.leave) { answer(row, "keep") }
        }
        // It deletes words: one line, asked once (owner 2026-11-04).
        .confirmationDialog(Copy.Sensitive.confirm, isPresented: Binding(
            get: { confirming == row.id }, set: { if !$0 { confirming = nil } })) {
            Button(Copy.Sensitive.remove, role: .destructive) { answer(row, "remove") }
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
        .accessibilityElement(children: .contain)
    }

    /// Optimistic: the row leaves at the answer and comes back with a toast if the answer never landed.
    private func answer(_ row: SensitiveRow, _ key: String) {
        answered.insert(row.id)
        Task {
            do {
                try await APIClient.shared.resolveSensitiveRow(id: item.id, row: row.id, key: key)
                await store.refresh([.inbox])
            } catch {
                answered.remove(row.id)
                store.toast = Copy.Sensitive.failed
            }
        }
    }
}
