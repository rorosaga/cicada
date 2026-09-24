import SwiftUI

/// "Look it up at" (G61; R-DG18 … R-DG20): where each fact on this page can be checked, said in words — which
/// fact a source backs up, how it can be read, who added it (with the app's mark) — so a person, or an agent they
/// point here, can check it before a question reaches them. It never says a source WAS checked: nothing on the
/// wire says so until G61 S3 (R-DI13). The page's open question closes the section with a way into the Inbox.
struct LookItUpSection: View {
    let entityId: String
    @Binding var sources: [EntitySource]
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @State private var newRef = ""

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Provenance.lookItUpAt)
            if !sources.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    ForEach(Array(sources.enumerated()), id: \.element.id) { index, source in
                        FactSourceRow(line: FactSourceWords.line(source), url: source.url) { remove(at: index) }
                    }
                }
                .padding(.horizontal, -CicadaTheme.scaled(10))
            }
            addField
            if let item = EntityOpenQuestion.first(in: store.visibleInbox, entityId: entityId) {
                openQuestion(item)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// The add field: a real input border (DR-9), a neutral Add with its ⏎ (DR-49), disabled until there is text.
    private var addField: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            TextField(Copy.Graph.addSourcePlaceholder, text: $newRef)
                .textFieldStyle(.plain)
                .font(CicadaTheme.font(size: 13))
                .foregroundStyle(CicadaTheme.textPrimary)
                .padding(.horizontal, CicadaTheme.spacingMD)
                .frame(height: CicadaTheme.scaled(32))
                .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBase))
                .ringed(.input, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                .onSubmit(add)
            NeutralButton(title: Copy.Graph.add, keyHint: "⏎", isDisabled: newRef.trimmed.isEmpty, action: add)
        }
    }

    private func openQuestion(_ item: InboxItem) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
            KindGlyph(kind: item.kind)
            Text(item.questionText)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(2)
            Spacer(minLength: 0)
            TextButton(title: Copy.Graph.openInInbox, help: Copy.Graph.openInInboxHelp) {
                // R-DG19 — the Inbox lands it in STATE 1 (`InboxPage.consumeLanding`).
                router.pendingInboxItem = item.id
                router.pendingTab = .inbox
            }
        }
        .padding(.top, CicadaTheme.spacingXS)
    }

    private func add() {
        let ref = newRef.trimmed
        guard !ref.isEmpty else { return }
        newRef = ""
        Task {
            if let updated = try? await APIClient.shared.addEntitySource(entityId: entityId, ref: ref) { sources = updated }
        }
    }

    private func remove(at index: Int) {
        Task {
            if let updated = try? await APIClient.shared.deleteEntitySource(entityId: entityId, index: index) { sources = updated }
        }
    }
}

/// One source: the ref (a link reads in `accentText`, `textPrimary` on a hovered fill — DR-6), then "For uses ·
/// Needs sign-in · [mark] Added by Claude Code · Sep 21", then one note when true; ↗ and remove at the end.
private struct FactSourceRow: View {
    let line: FactSourceWords.Line
    let url: URL?
    let onRemove: () -> Void
    @State private var hovering = false

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.scaled(10)) {
            Image(systemName: line.isLink ? "link" : "doc")
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(.top, CicadaTheme.scaled(3))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(line.ref)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(line.isLink ? (hovering ? CicadaTheme.textPrimary : CicadaTheme.accentText)
                                                 : CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .help(line.help)
                HStack(spacing: CicadaTheme.spacingXS) {
                    Text(line.forFact)
                    if let readBy = line.readBy {
                        Text("·").accessibilityHidden(true)
                        Text(readBy)
                    }
                    Text("·").accessibilityHidden(true)
                    if let origin = line.addedByOrigin {
                        OriginMark(origin: origin, size: CicadaTheme.scaled(12))
                    }
                    Text(line.addedBy)
                }
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                if let note = line.note {
                    Text(note).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            Spacer(minLength: 0)
            if let url {
                IconButton(systemName: "arrow.up.right", help: Copy.Graph.openSource(line.ref)) { NSWorkspace.shared.open(url) }
            }
            IconButton(systemName: "trash", help: Copy.Graph.removeSource, action: onRemove)
        }
        .padding(.leading, CicadaTheme.scaled(10))
        .padding(.trailing, CicadaTheme.spacingXS)
        .padding(.vertical, CicadaTheme.scaled(6))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(hovering ? CicadaTheme.bgHover : Color.clear))
        .onHover { hovering = $0 }
    }
}
