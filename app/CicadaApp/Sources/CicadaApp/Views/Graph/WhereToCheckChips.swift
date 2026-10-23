import SwiftUI

/// G61 "Where to check" (ruling 36 D5; owner 2026-10-22: "shown like this at the top of the entity page") — the page's
/// places to check as one compact row of chips at the top of the card: a site's own icon only where the existing rule
/// serves one (`iconSite`: a trusted site on a page that is not a person, G159), else the link kind's glyph; a click
/// opens it, a right-click removes it, `+` adds one. A proposed link waits in the Inbox, not here. Then a small `?`:
/// how pages fade (it replaced Settings' Memory page). The list is read when the card opens and held on the card
/// (`GET /entities/{id}/sources`, not a Store domain); writes go through `Store.perform` like the section below.
struct WhereToCheckChips: View {
    let entityId: String
    var isCurrent: () -> Bool = { true }

    @Environment(Store.self) private var store
    @State private var sources: [EntitySource] = []
    @State private var adding = false
    @State private var draft = ""
    @State private var showsFade = false
    @State private var writes = SourceWriteQueue()

    /// What the row shows: links, not waiting proposals, not notes (a note is words, read in the section below).
    static func chips(_ sources: [EntitySource]) -> [EntitySource] {
        sources.filter { $0.proposed != true && $0.kind == "url" && $0.url != nil }
    }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    ForEach(Self.chips(sources)) { chip($0) }
                    // With no chips yet, a lone "Add" said nothing about what it adds (looks pass 2026-10-23).
                    TextButton(title: Self.chips(sources).isEmpty ? Copy.WhereChips.add : Copy.WhereChips.addShort,
                               help: Copy.WhereChips.add, flushLeading: Self.chips(sources).isEmpty) { adding = true }
                        .popover(isPresented: $adding, arrowEdge: .bottom) { addField }
                }
            }
            IconButton(systemName: "questionmark.circle", help: Copy.WhereChips.fadeHelp) { showsFade = true }
                .popover(isPresented: $showsFade, arrowEdge: .bottom) { fadeExplainer }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Copy.WhereChips.label)
        .task(id: entityId) {
            sources = []
            if let fresh = try? await APIClient.shared.fetchEntitySources(entityId: entityId), isCurrent() {
                sources = fresh
            }
        }
    }

    private func chip(_ source: EntitySource) -> some View {
        let words = LinkWords.of(ref: source.ref, label: source.label, linkKind: source.linkKind)
        return Button {
            if let url = source.url { NSWorkspace.shared.open(url) }
        } label: {
            HStack(spacing: CicadaTheme.scaled(5)) {
                if let site = source.iconSite {
                    SiteIcon(site: site, size: .inline, entity: entityId)
                } else {
                    Image(systemName: LinkKindGlyph.symbol(words.kind))
                        .font(CicadaTheme.icon(.inline))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                Text(words.label)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
            }
            .padding(.horizontal, CicadaTheme.scaled(8))
            .frame(height: CicadaTheme.scaled(24))
            .background(CicadaTheme.bgSelected, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        }
        .buttonStyle(.cicadaPlain)
        .help(Copy.WhereChips.open(source.ref))
        .contextMenu {
            Button(Copy.WhereChips.remove, role: .destructive) { remove(source) }
        }
    }

    private var addField: some View {
        TextField("", text: $draft)
            .textFieldStyle(.plain)
            .cicadaField(prompt: Copy.WhereChips.addPrompt, isEmpty: draft.isEmpty)
            .frame(width: CicadaTheme.scaled(280))
            .padding(CicadaTheme.spacingMD)
            .onSubmit { add() }
    }

    private var fadeExplainer: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(Copy.WhereChips.fadeTitle).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
            Text(Copy.WhereChips.fadeBody).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(width: CicadaTheme.scaled(300), alignment: .leading)
        .padding(CicadaTheme.spacingMD)
    }

    private func add() {
        let ref = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !ref.isEmpty else { return }
        let mutation = EntitySourceAdd(entityId: entityId, ref: ref, predicate: nil, sources: $sources,
                                       isCurrent: isCurrent)
        writes.run {
            if await store.perform(mutation) {
                draft = ""
                adding = false
                await SiteIconStore.shared.forget(entity: entityId)
            }
        }
    }

    private func remove(_ source: EntitySource) {
        let mutation = EntitySourceWrite(entityId: entityId, source: source, change: .remove, sources: $sources,
                                         isCurrent: isCurrent)
        writes.run {
            if await store.perform(mutation), let words = SourceChange.remove.doneMessage { store.toast = words }
        }
    }
}
