import SwiftUI

/// G246 (ruling 81, plan 1.6) — one dated line on Home when saved posts moved under their lists: "412 saved posts now
/// show under their lists (since 24 Nov). Open one to keep it as a page." So thousands of dots do not just disappear
/// from the graph without a word. It reads `GraphResponse.hiddenPosts`, which is 0 until the posts-as-rows switch is on,
/// so nothing draws before then. The day is the first day this Mac read a number; the line goes after a month or at
/// "Got it" (`HiddenPostsNote`, this Mac's own record, never the bank).
///
/// Applies DR-25's quiet rows (a one-line row, `metaFont`, `textSecondary`), DR-40 (a neutral compact button), DR-21 (the
/// count is formatted by `UsageFormat`), DR-2 (no colour beyond the text ladder).
struct HiddenPostsStrip: View {
    @Environment(Store.self) private var store
    /// This Mac's record for this memory, read when the number changes (never from `body`: reading it may stamp the day).
    @State private var record: HiddenPostsNote.Record?

    var body: some View {
        let hidden = store.graph.value?.hiddenPosts ?? 0
        Group {
            if let line = HiddenPostsNote.line(hidden: hidden, record: record) { row(line) }
        }
        .onChange(of: hidden, initial: true) { _, now in record = HiddenPostsNote.observe(hidden: now, bank: store.bank) }
        .onChange(of: store.bank) { _, _ in record = HiddenPostsNote.observe(hidden: hidden, bank: store.bank) }
    }

    private func row(_ line: String) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(line)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: CicadaTheme.spacingSM)
            NeutralButton(title: Copy.Keep.gotIt, size: .compact) {
                HiddenPostsNote.dismiss(bank: store.bank)
                record = HiddenPostsNote.load(bank: store.bank)
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
    }
}
