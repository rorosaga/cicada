import SwiftUI

/// "Look it up at" (G61; R-DG18 … R-DG20): where each fact on this page can be checked, said in words — which
/// fact a source backs up, how it can be read, who added it (with the app's mark) — so a person, or an agent they
/// point here, can check it before a question reaches them. It never says a source WAS checked: nothing on the
/// wire says so until G61 S3 (R-DI13). The page's open question closes the section with a way into the Inbox.
struct LookItUpSection: View {
    let entityId: String
    /// The page's type, for what the empty field asks for: a brand its official website, a person a profile.
    var entityType: EntityType? = nil
    @Binding var sources: [EntitySource]
    /// Opens another page's card (the card's own `navigate(to:)`) — a source's "Open page ›".
    var navigate: (String) -> Void = { _ in }
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @State private var newRef = ""
    /// The row whose inline editor is open (a fact to type, or a page to pick), by `EntitySource.id`.
    @State private var editing: SourceEditing?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Provenance.lookItUpAt)
            if !sources.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    // A page holds many sources; each fact's are together, in words (G61 S3-a).
                    ForEach(SourceGroups.groups(sources)) { group in
                        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                            if SourceGroups.groups(sources).count > 1 {
                                Text(group.title)
                                    .font(CicadaTheme.metaFont)
                                    .foregroundStyle(CicadaTheme.textSecondary)
                                    .padding(.leading, CicadaTheme.scaled(10))
                                    .padding(.top, CicadaTheme.spacingXS)
                            }
                            ForEach(group.rows) { source in
                                row(source)
                                if editing?.id == source.id, let editing { editor(editing, for: source) }
                            }
                        }
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

    private func row(_ source: EntitySource) -> some View {
        let linked = source.entity.flatMap { id in store.entityNames.name(for: id).map { (id: id, name: $0) } }
        return FactSourceRow(
            line: FactSourceWords.line(source), url: source.url, linked: linked,
            node: linked.flatMap { pair in store.graph.value?.nodes.first { $0.id == pair.id } },
            canBeTaken: source.canBeTaken,
            entityId: entityId, site: SourceSite.key(of: source),
            isUnconfirmedSite: source.isUnconfirmedSite,
            drawsMark: [.company, .tool].contains(entityType),
            // A Contacts card is the Contacts sync's: it can be removed, never edited or re-linked here.
            isManaged: !source.ref.hasPrefix("addressbook://"),
            onOpenPage: { if let linked { navigate(linked.id) } },
            onChange: { change in write(change, on: source) },
            onEdit: { mode in editing = SourceEditing(id: source.id, mode: mode) })
    }

    @ViewBuilder
    private func editor(_ state: SourceEditing, for source: EntitySource) -> some View {
        switch state.mode {
        case .fact:
            SourceFactEditor(initial: SourceGroups.title(source.predicate) == Copy.Graph.sourcesAnything ? "" :
                                (source.predicate ?? "").replacingOccurrences(of: "-", with: " ")) { text in
                editing = nil
                write(.fact(text), on: source)
            } cancel: { editing = nil }
        case .link:
            SourceLinkPicker(entityId: entityId, nodes: store.graph.value?.nodes ?? []) { id in
                editing = nil
                write(.link(id), on: source)
            } cancel: { editing = nil }
        }
    }

    /// The add field: a real input border (DR-9), a neutral Add with its ⏎ (DR-49), disabled until there is text.
    private var addField: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            TextField(placeholder, text: $newRef)
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

    /// A brand page asks for its site, a person's for a profile (G61 S3-b) — what an agent would want to look at first.
    private var placeholder: String {
        switch entityType {
        case .company?, .tool?, .project?: Copy.Graph.sourcePlaceholderSite
        case .person?: Copy.Graph.sourcePlaceholderProfile
        default: Copy.Graph.addSourcePlaceholder
        }
    }

    private var addsSite: Bool { [.company, .tool, .project].contains(entityType) }

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
        // A link typed on a brand page is its official site: the person's own word, trusted at once (G61 S3-b).
        let predicate = addsSite && ref.lowercased().hasPrefix("http")
            && !sources.contains { $0.isOfficialSite && ($0.trusted ?? true) } ? "website" : nil
        Task {
            if let updated = try? await APIClient.shared.addEntitySource(entityId: entityId, ref: ref, predicate: predicate) {
                sources = updated
                await SiteIconStore.shared.forget(entity: entityId)   // a 404 from before this site was trusted is stale
                await store.refresh([.graph])   // its picture is drawn from a trusted site
            }
        }
    }

    /// One edit, painted at once and rolled back with the server's sentence (`EntitySourceWrite`).
    private func write(_ change: SourceChange, on source: EntitySource) {
        let mutation = EntitySourceWrite(entityId: entityId, source: source, change: change, sources: $sources)
        Task {
            let landed = await store.perform(mutation)
            if landed { await SiteIconStore.shared.forget(entity: entityId) }   // "Use this site" makes its mark available
            if landed, let words = change.doneMessage { store.toast = words }
        }
    }
}

/// Which inline editor is open under which row.
struct SourceEditing: Equatable {
    enum Mode: Equatable { case fact, link }
    let id: String
    let mode: Mode
}

/// "What is it for?" — a fact typed in words, applied with ⏎ (a keyboard action never animates).
private struct SourceFactEditor: View {
    let initial: String
    let apply: (String) -> Void
    let cancel: () -> Void
    @State private var text = ""

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            TextField(Copy.Graph.factPrompt, text: $text)
                .textFieldStyle(.plain)
                .font(CicadaTheme.font(size: 13))
                .foregroundStyle(CicadaTheme.textPrimary)
                .padding(.horizontal, CicadaTheme.spacingMD)
                .frame(height: CicadaTheme.scaled(30))
                .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBase))
                .ringed(.input, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                .onSubmit { apply(text) }
                .onExitCommand(perform: cancel)
            NeutralButton(title: Copy.Graph.apply, keyHint: "⏎", isDisabled: false) { apply(text) }
            TextButton(title: Copy.Graph.cancel, help: Copy.Graph.cancel, action: cancel)
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .onAppear { text = initial }
    }
}

/// "Link to a page" — a find field and the pages that match, by the palette's own ranker. A source never creates a
/// page: only one that already exists is offered.
private struct SourceLinkPicker: View {
    let entityId: String
    let nodes: [GraphNode]
    let pick: (String) -> Void
    let cancel: () -> Void
    @State private var query = ""

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                CicadaSearchField(text: $query, prompt: Copy.Graph.linkSearchPrompt, findEnabled: false,
                                  autofocus: true, onEscape: cancel)
                TextButton(title: Copy.Graph.cancel, help: Copy.Graph.cancel, action: cancel)
            }
            let hits = SourceLinkCandidates.matching(query, nodes: nodes, excluding: entityId)
            if !query.trimmed.isEmpty, hits.isEmpty {
                Text(Copy.Graph.linkNoMatch).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            ForEach(hits, id: \.id) { node in
                Button { pick(node.id) } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        EntityPicture(id: node.id, name: node.name, type: node.type, size: 20)
                        Text(node.name).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                        Spacer(minLength: 0)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
    }
}

/// One source: the ref (a link reads in `accentText`, `textPrimary` on a hovered fill — DR-6), then "For uses ·
/// Needs sign-in · [mark] Added by Claude Code · Sep 21", then one note when true; ↗ and a menu at the end. A source
/// linked to its own page wears that page's picture and offers "Open page ›" (G61 S3-a).
private struct FactSourceRow: View {
    let line: FactSourceWords.Line
    let url: URL?
    /// The page this source is linked to, when it still exists.
    let linked: (id: String, name: String)?
    let node: GraphNode?
    let canBeTaken: Bool
    let entityId: String
    /// The site whose mark leads the row (a url source only).
    let site: String?
    let isUnconfirmedSite: Bool
    /// Only a company or tool page draws a mark from its site; on any other page "Use this site" only trusts it.
    let drawsMark: Bool
    let isManaged: Bool
    let onOpenPage: () -> Void
    let onChange: (SourceChange) -> Void
    let onEdit: (SourceEditing.Mode) -> Void
    @State private var hovering = false

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.scaled(10)) {
            mark
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
            if isUnconfirmedSite {
                // "Not confirmed — Use this site?": one tap trusts it and its mark is drawn from it (G61 S3-b).
                TextButton(title: Copy.Graph.useThisSite,
                           help: drawsMark ? Copy.Graph.useThisSiteHelp : Copy.Graph.useThisSiteHelpNoMark) { onChange(.useThis) }
            }
            if let linked {
                TextButton(title: Copy.Graph.openLinkedPage, help: Copy.Graph.openLinkedPageHelp(linked.name), action: onOpenPage)
            }
            if let url {
                IconButton(systemName: "arrow.up.right", help: Copy.Graph.openSource(line.ref)) { NSWorkspace.shared.open(url) }
            }
            menu
        }
        .padding(.leading, CicadaTheme.scaled(10))
        .padding(.trailing, CicadaTheme.spacingXS)
        .padding(.vertical, CicadaTheme.scaled(6))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(hovering ? CicadaTheme.bgHover : Color.clear))
        .onHover { hovering = $0 }
    }

    /// The linked page's own picture (its "own memory node"), else the kind's glyph.
    @ViewBuilder
    private var mark: some View {
        if let linked, let node {
            EntityPicture(id: linked.id, name: linked.name, type: node.type, size: 20)
                .padding(.top, CicadaTheme.scaled(1))
        } else if let site, line.isLink {
            SiteIcon(site: site, size: .inline, entity: entityId)
                .padding(.top, CicadaTheme.scaled(2))
        } else {
            Image(systemName: line.isLink ? "link" : "doc")
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(.top, CicadaTheme.scaled(3))
                .accessibilityHidden(true)
        }
    }

    /// Change what it is for or how it is read, link it to a page, take an agent's, or remove it.
    private var menu: some View {
        Menu {
            if isManaged {
                if canBeTaken {
                    Button(isUnconfirmedSite ? Copy.Graph.useThisSite : Copy.Graph.useThisSource) { onChange(.useThis) }
                    Divider()
                }
                Button(Copy.Graph.changeFact) { onEdit(.fact) }
                Button(Copy.Graph.readAsPublic) { onChange(.access("public")) }
                Button(Copy.Graph.readAsSignedIn) { onChange(.access("signed_in")) }
                Divider()
                if linked != nil {
                    Button(Copy.Graph.unlinkPage) { onChange(.unlink) }
                }
                Button(Copy.Graph.linkToPage) { onEdit(.link) }
                Divider()
            }
            Button(Copy.Graph.removeSource, role: .destructive) { onChange(.remove) }
        } label: {
            Image(systemName: "ellipsis")
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .help(Copy.Graph.sourceMenu)
        .accessibilityLabel(Copy.Graph.sourceMenu)
    }
}

/// The site a source row's mark is asked for: a `url` source's own site (`reading_hosts.site_of`'s twin — the host
/// without `www.`, the last two labels). The server answers only for a trusted site of the page, and the key is the site,
/// never the URL, so no path or token leaves the app in a request.
enum SourceSite {
    static func key(of source: EntitySource) -> String? {
        guard source.kind == "url", let host = URL(string: source.ref)?.host?.lowercased(), !host.isEmpty else { return nil }
        var labels = host.hasPrefix("www.") ? String(host.dropFirst(4)).split(separator: ".") : host.split(separator: ".")
        guard labels.count >= 2 else { return nil }
        let secondLevel: Set<Substring> = ["co", "com", "org", "net", "gov", "edu", "ac"]
        let keep = (labels.last!.count == 2 && secondLevel.contains(labels[labels.count - 2])) ? 3 : 2
        labels = Array(labels.suffix(keep))
        return labels.joined(separator: ".")
    }
}
