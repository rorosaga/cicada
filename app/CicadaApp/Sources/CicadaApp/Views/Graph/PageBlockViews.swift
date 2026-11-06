import AppKit
import SwiftUI

// MARK: - The entity page's blocks (ruling 48, 2026-10-28; DR-78…DR-81)
//
// Each block draws what `GET /entities/{id}`'s `blocks` hold and nothing else: an absent block draws nothing, an open
// block holds at most five rows, and nothing on the page folds (DR-81). The card lays them out in DR-78's order.

// MARK: In short (DR-78)

/// Where Sleep's 2–3 sentence summary lands (ruling 48 (5), part B). Until a page has one, the slot holds the served
/// why-it-matters line and, under it, what a person's facts strip used to repeat (ruling 48 (3)): how many
/// conversations, and the latest.
struct PageInShort: View {
    let relevance: EntityRelevance?
    var today: ISODay = .today()

    /// Whether the In short slot draws for this page: never for an added file (its own Why it matters), and never the
    /// "no personal relation" line on a book (G233, DR-38: the head already says how it came in). A relation that
    /// exists still shows.
    static func isDrawn(relevance: EntityRelevance?, media: MediaBlock?) -> Bool {
        if media?.isFile == true { return false }
        if media?.isBook == true, (relevance?.tense ?? "none") == "none" { return false }
        return true
    }

    static func counts(_ r: EntityRelevance?, today: ISODay) -> String? {
        guard let r, r.conversations > 0 else { return nil }
        var parts = [Copy.Pages.conversations(r.conversations)]
        if let last = ISODay(r.lastMentioned) {
            parts.append("the latest \(RelativeDay.phrase(last, today: today).lowercasedFirst)")
        }
        return parts.joined(separator: " · ")
    }

    var body: some View {
        if let line = relevance?.shownLine {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
                Text(line)
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineSpacing(CicadaTheme.scaled(2))
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                    .accessibilityIdentifier("entity-relevance")
                if let counts = Self.counts(relevance, today: today) {
                    Text(counts).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

// MARK: Where to check (DR-79)

/// One box of mention rows near the top of the page: the site in tertiary, the link's own words in primary ink, its
/// state in words on the trailing edge. A person's rows draw the link's kind, never a site's icon (G159); proposals are
/// one "N suggested links · Review" line (ruling 36 D5). At most five rows, then "All N". A click opens the link; a
/// right-click removes it; *Add a link* adds one. The rows come with the page (`blocks.sources`) — opening a page reads
/// nothing more; the full entries are read only when the person changes one.
struct WhereToCheckBox: View {
    let entityId: String
    let isPerson: Bool
    let sources: PageBlocks.Sources?
    /// The add field is open — from *Add a link* here, or the page's menu when the page has no link yet.
    @Binding var adding: Bool
    /// Re-reads the page after a write, so the box shows the server's answer.
    var onChanged: () -> Void = {}
    var isCurrent: () -> Bool = { true }
    var today: ISODay = .today()

    @Environment(Store.self) private var store
    @State private var draft = ""
    @State private var showsAll = false
    @State private var reviewing = false
    @State private var entries: [EntitySource] = []
    @State private var writes = SourceWriteQueue()

    static let maxRows = 5

    var body: some View {
        let rows = PageWords.rows(sources)
        let waiting = PageWords.proposals(sources)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                SectionLabel(rows.isEmpty ? Copy.Pages.whereToCheck : "\(Copy.Pages.whereToCheck) · \(rows.count)")
                Spacer(minLength: 0)
                TextButton(title: Copy.Pages.addLink, inline: true) { adding = true }
                    .popover(isPresented: $adding, arrowEdge: .bottom) { addField }
            }
            if !rows.isEmpty || waiting > 0 {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(rows.prefix(Self.maxRows), id: \.ref) { row($0) }
                    if rows.count > Self.maxRows || waiting > 0 {
                        HStack(spacing: CicadaTheme.spacingSM) {
                            if rows.count > Self.maxRows {
                                TextButton(title: Copy.Pages.all(rows.count), inline: true) { showsAll = true }
                                    .popover(isPresented: $showsAll, arrowEdge: .bottom) { allRows(rows) }
                            }
                            Spacer(minLength: 0)
                            if waiting > 0 {
                                Text(Copy.Pages.suggested(waiting))
                                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                                TextButton(title: Copy.Pages.review, inline: true) { review() }
                                    .popover(isPresented: $reviewing, arrowEdge: .bottom) { proposals }
                            }
                        }
                        .padding(.horizontal, CicadaTheme.spacingMD)
                        .padding(.vertical, CicadaTheme.spacingXS)
                    }
                }
                .padding(.vertical, CicadaTheme.spacingXS)
                .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgOption))
                .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Copy.Pages.whereToCheck)
    }

    private func row(_ source: PageBlocks.Source) -> some View {
        let words = PageWords.mention(source)
        return Button {
            if let url = URL(string: source.ref), url.scheme != nil { NSWorkspace.shared.open(url) }
        } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                glyph(source)
                    .frame(width: CicadaTheme.scaled(16))
                if let site = words.site {
                    Text(site).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                }
                Text(words.title)
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .underline(true, color: CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(PageWords.state(source, today: today))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
            .frame(minHeight: CicadaTheme.scaled(36))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(Copy.Pages.open(source.ref))
        .contextMenu {
            Button(Copy.Pages.remove, role: .destructive) { change(source.ref, .remove) }
        }
    }

    /// G159 — a person's links draw their kind; a site's icon only where the server serves one (`iconSite`).
    @ViewBuilder
    private func glyph(_ source: PageBlocks.Source) -> some View {
        if !isPerson, let site = source.iconSite {
            SiteIcon(site: site, size: .inline, entity: entityId)
        } else {
            Image(systemName: LinkKindGlyph.symbol(source.linkKind ?? (source.kind == "url" ? "website" : "note")))
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    private func allRows(_ rows: [PageBlocks.Source]) -> some View {
        ScrollView {
            // Lazy, like every "All N" (inbox freeze, 2026-10-29): the popover opens at once however long the list.
            LazyVStack(alignment: .leading, spacing: 0) { ForEach(rows, id: \.ref) { row($0) } }
                .padding(.vertical, CicadaTheme.spacingXS)
        }
        .frame(width: CicadaTheme.scaled(520))
        .frame(maxHeight: CicadaTheme.scaled(420))
    }

    private var proposals: some View {
        let waiting = entries.filter { $0.proposed == true }
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(waiting) { source in
                HStack(spacing: CicadaTheme.spacingSM) {
                    let words = LinkWords.of(ref: source.ref, label: source.label, linkKind: source.linkKind)
                    Image(systemName: LinkKindGlyph.symbol(words.kind))
                        .font(CicadaTheme.icon(.inline)).foregroundStyle(CicadaTheme.textTertiary)
                    Text(words.label).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1).truncationMode(.middle)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    NeutralButton(title: Copy.Pages.useThis, size: .compact) { change(source.ref, .useThis) }
                    TextButton(title: Copy.Pages.notThis, inline: true) { change(source.ref, .remove) }
                }
            }
            if waiting.isEmpty { SectionLoading(text: Copy.Graph.readingSources) }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: CicadaTheme.scaled(440), alignment: .leading)
    }

    private var addField: some View {
        TextField("", text: $draft)
            .textFieldStyle(.plain)
            .cicadaField(prompt: Copy.Pages.addPrompt, isEmpty: draft.isEmpty)
            .frame(width: CicadaTheme.scaled(280))
            .padding(CicadaTheme.spacingMD)
            .onSubmit { add() }
    }

    /// The full entries, read once the person changes something (a write is keyed by the entry's `(ref, predicate)`).
    private func loadEntries() async -> Bool {
        if !entries.isEmpty { return true }
        guard let fresh = try? await APIClient.shared.fetchEntitySources(entityId: entityId), isCurrent() else {
            return false
        }
        entries = fresh
        return true
    }

    private func review() {
        reviewing = true
        Task { _ = await loadEntries() }
    }

    private func change(_ ref: String, _ change: SourceChange) {
        writes.run {
            guard await loadEntries(), let source = entries.first(where: { $0.ref == ref }) else { return }
            let mutation = EntitySourceWrite(entityId: entityId, source: source, change: change,
                                             sources: $entries, isCurrent: isCurrent)
            if await store.perform(mutation) {
                if let words = change.doneMessage { store.toast = words }
                onChanged()
            }
        }
    }

    private func add() {
        let ref = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !ref.isEmpty else { return }
        let mutation = EntitySourceAdd(entityId: entityId, ref: ref, predicate: nil, sources: $entries,
                                       isCurrent: isCurrent)
        writes.run {
            if await store.perform(mutation) {
                draft = ""
                adding = false
                await SiteIconStore.shared.forget(entity: entityId)
                onChanged()
            }
        }
    }
}

// MARK: Marks (ruling 64)

/// Ruling 64: what the person marked in this book, word for word. A passage reads as a quote in the book's voice, the note
/// under it as their own (DR-3, DR-78).
struct PageMarks: View {
    let marks: PageBlocks.Marks
    var entityId: String? = nil
    @Environment(ProvenanceRouter.self) private var router: ProvenanceRouter?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel("\(Copy.Pages.marked) · \(UsageFormat.count(marks.total))")
            ForEach(marks.items, id: \.claimId) { item in
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    if let text = item.text {
                        Text(text)
                            .font(CicadaTheme.bodyFont)
                            .italic()
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                            .textSelection(.enabled)
                    }
                    if let note = item.note {
                        Text(note)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                            .textSelection(.enabled)
                    }
                    HStack(spacing: CicadaTheme.spacingSM) {
                        if let day = item.day, !day.isEmpty {
                            Text(day).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                        }
                        // ROR-16 (DR-31): a mark points at its own words in the record, as any citation does.
                        if let router, let target = item.evidence.flatMap({ ReaderTarget.evidence($0, subjectId: entityId) }) {
                            TextButton(title: Copy.Provenance.showIn(SpanSourceKind.book) + " ›") { router.open(target) }
                                .fixedSize()
                        }
                    }
                }
            }
            if marks.total > marks.items.count {
                Text(Copy.Pages.markedMore(marks.total - marks.items.count))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        }
    }
}

// MARK: Ongoing (ruling 48 (4))

/// Open threads and planned dates on any page (G141's open happenings and milestones), each on the Projects band's
/// hollow node. At most five, then the count. It replaced a person's *What's happening*.
struct PageOngoing: View {
    let items: [PageBlocks.Ongoing]
    let total: Int
    var today: ISODay = .today()

    static let maxRows = 5

    var body: some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                SectionLabel("\(Copy.Pages.ongoing) · \(UsageFormat.count(max(total, items.count)))")
                VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                    ForEach(items.prefix(Self.maxRows), id: \.claimId) { item in
                        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingMD) {
                            Circle()
                                .strokeBorder(CicadaTheme.textSecondary, lineWidth: 1.5)
                                .frame(width: CicadaTheme.scaled(8), height: CicadaTheme.scaled(8))
                                .accessibilityHidden(true)
                            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                                Text(item.text)
                                    .font(CicadaTheme.bodyFont)
                                    .foregroundStyle(CicadaTheme.textPrimary)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .textSelection(.enabled)
                                let meta = PageWords.ongoingMeta(item, today: today)
                                if !meta.isEmpty {
                                    Text(meta).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                                }
                            }
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

// MARK: Belief sentences (DR-80)

/// A page whose prose cites nothing yet carries its beliefs as sentences of one paragraph, each with its markers — an
/// ended one says until when, an inference says so — never a list. Past twelve, the rest are in Perspectives.
struct PageBeliefSentences: View {
    let entityId: String
    let beliefs: [PageBlocks.Citations.Belief]
    /// The link past the sentences ("3 more in Perspectives"), if there is more than is drawn — decided by the card,
    /// which counts the older facts too (`PageWords.moreBeliefs`).
    var more: String? = nil
    var onMore: () -> Void = {}
    @State private var open: CiteKey?

    var body: some View {
        if !beliefs.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                beliefs.reduce(Text(verbatim: "")) { text, belief in
                    let keys = belief.refs.map { CiteKey(n: $0, claim: belief.claimId, inferred: belief.inferred) }
                    return text + Text(PageWords.sentence(belief)) + CitationMarks.text(keys) + Text(verbatim: " ")
                }
                .font(CicadaTheme.bodyFont)
                .lineSpacing(CicadaTheme.scaled(2))
                .foregroundStyle(CicadaTheme.textPrimary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .modifier(CitationLinkHandler(open: $open))
                .modifier(CitationActions(keys: beliefs.flatMap { belief in
                    belief.refs.map { CiteKey(n: $0, claim: belief.claimId, inferred: belief.inferred) }
                }, open: $open))
                .popover(item: $open, arrowEdge: .bottom) { CitationPopover(entityId: entityId, key: $0) }
                if let more {
                    TextButton(title: more, inline: true, flushLeading: true, action: onMore)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

// MARK: Older facts (ROR-129, ruling 70)

/// The facts that have faded, at the end of the article: quiet text in the tertiary ink, newest as the server sent
/// them, never a fold (DR-81), never closed or hidden — Ask, recall and agents still read them as before. Each sentence
/// opens a small popover with *Keep this fact* (the person's word that it stays), so the control is reachable even for a
/// fact with no source marker; a source marker opens the citation popover, which carries the same control.
struct PageOlderFacts: View {
    let entityId: String
    let facts: [PageBlocks.Citations.Belief]
    /// "N more in Perspectives" past what is drawn, or nil.
    var more: String? = nil
    var onMore: () -> Void = {}
    @State private var open: CiteKey?
    @State private var keeping: String?

    static let scheme = "cicada", host = "older"

    static func url(_ claimId: String) -> URL? {
        var parts = URLComponents()
        parts.scheme = scheme
        parts.host = host
        parts.path = "/" + claimId
        return parts.url
    }

    private var text: Text {
        facts.reduce(Text(verbatim: "")) { out, fact in
            var sentence = AttributedString(PageWords.sentence(fact))
            sentence.foregroundColor = CicadaTheme.textTertiary
            sentence.link = Self.url(fact.claimId)
            let keys = fact.refs.map { CiteKey(n: $0, claim: fact.claimId, inferred: fact.inferred) }
            return out + Text(sentence) + CitationMarks.text(keys) + Text(verbatim: " ")
        }
    }

    var body: some View {
        if !facts.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                SectionLabel(Copy.Pages.olderFacts)
                text
                    .font(CicadaTheme.bodyFont)
                    .lineSpacing(CicadaTheme.scaled(2))
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .environment(\.openURL, OpenURLAction { url in
                        if url.scheme == Self.scheme, url.host == Self.host {
                            keeping = String(url.path.dropFirst())
                            return .handled
                        }
                        if let key = CiteKey(url: url) {
                            open = key
                            return .handled
                        }
                        return .systemAction
                    })
                    .modifier(KeepActions(facts: facts) { keeping = $0 })
                    .popover(item: $open, arrowEdge: .bottom) { CitationPopover(entityId: entityId, key: $0) }
                    .popover(item: Binding(get: { keeping.map(FactID.init) }, set: { keeping = $0?.id }),
                             arrowEdge: .bottom) { fact in
                        KeepFactPopover(entityId: entityId, claimId: fact.id)
                    }
                if let more {
                    TextButton(title: more, inline: true, flushLeading: true, action: onMore)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private struct FactID: Identifiable { let id: String }

    /// VoiceOver reaches each older fact's control without finding a link inside the paragraph.
    private struct KeepActions: ViewModifier {
        let facts: [PageBlocks.Citations.Belief]
        let open: (String) -> Void

        func body(content: Content) -> some View {
            facts.reduce(AnyView(content)) { view, fact in
                AnyView(view.accessibilityAction(named: Copy.Pages.keepNamed(fact.text)) { open(fact.claimId) })
            }
        }
    }
}

/// What a faded sentence opens: it has not been mentioned lately, and the one control — *Keep this fact*.
private struct KeepFactPopover: View {
    let entityId: String
    let claimId: String
    @Environment(\.dismiss) private var dismiss
    @State private var kept = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(Copy.Pages.olderExplained)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            TextButton(title: kept ? Copy.Pages.factKept : Copy.Pages.keepFact) {
                guard !kept else { return }
                kept = true
                Task {
                    do {
                        try await APIClient.shared.keepFact(entityId: entityId, claimId: claimId, keep: true)
                        dismiss()
                    } catch { kept = false }
                }
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: CicadaTheme.scaled(260), alignment: .leading)
    }
}

// MARK: References (DR-80)

/// Always open, closing the page: numbered sources, one line each, at most six, then the line that says how many in
/// all and that who wrote each change is in History.
struct PageReferences: View {
    let citations: PageBlocks.Citations
    let onHistory: () -> Void
    var today: ISODay = .today()

    var body: some View {
        if !citations.refs.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                HStack(alignment: .firstTextBaseline) {
                    SectionLabel(Copy.Pages.references)
                    Spacer(minLength: 0)
                    TextButton(title: Copy.Pages.history, help: Copy.Pages.historyHelp, inline: true, action: onHistory)
                }
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                    ForEach(citations.refs) { ref in
                        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                            Text(verbatim: String(ref.n))
                                .font(CicadaTheme.metaFont.monospacedDigit())
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .frame(width: CicadaTheme.scaled(16), alignment: .leading)
                            Text(line(ref))
                                .font(CicadaTheme.metaFont)
                                .lineLimit(1)
                                .truncationMode(.tail)
                            Spacer(minLength: CicadaTheme.spacingSM)
                            if let when = PageWords.refWhen(first: ref.first, last: ref.last, today: today) {
                                Text(when).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                                    .lineLimit(1)
                            }
                        }
                    }
                }
                if let closing = PageWords.closingLine(citations) {
                    Text(closing)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func line(_ ref: PageBlocks.Citations.Ref) -> AttributedString {
        var who = AttributedString(PageWords.refWho(ref))
        who.foregroundColor = CicadaTheme.textSecondary
        guard let title = ref.title, !title.isEmpty else { return who }
        var rest = AttributedString(" · \(title)")
        rest.foregroundColor = CicadaTheme.textPrimary
        return who + rest
    }
}

// MARK: The brand block (ruling 48 (7))

/// A page saved for its look leads with its brand, drawn from the looks the page holds (`blocks.looks`): the palette as
/// swatches with copyable hex (DR-19; the page's own colours are data, DR-8), the type set in the look's own faces (a
/// specimen is data, 2026-10-15), and *Copy as tokens*. The look tiles follow (`PageLooksSection`).
struct PageBrandBlock: View {
    let looks: [PageBlocks.Look]
    @Environment(Store.self) private var store

    static func palette(_ looks: [PageBlocks.Look]) -> [String] {
        var seen = Set<String>()
        return looks.flatMap { $0.palette ?? [] }.filter { seen.insert($0.uppercased()).inserted }.prefix(6).map { $0 }
    }

    static func fonts(_ looks: [PageBlocks.Look]) -> [String] {
        var seen = Set<String>()
        return looks.flatMap { $0.fonts ?? [] }.filter { seen.insert($0.lowercased()).inserted }.prefix(2).map { $0 }
    }

    /// The palette and type as CSS variables, for an agent or the person to build with.
    static func tokens(_ looks: [PageBlocks.Look]) -> String {
        var lines = [":root {"]
        for (i, hex) in palette(looks).enumerated() { lines.append("  --brand-color-\(i + 1): \(hex);") }
        for (i, face) in fonts(looks).enumerated() { lines.append("  --brand-font-\(i + 1): \"\(face)\";") }
        lines.append("}")
        return lines.joined(separator: "\n")
    }

    /// Ruling 48 (7): the brand leads when looks are what the page is about — two or more, or a page with no article.
    static func leads(looks: Int, articleEmpty: Bool) -> Bool { looks >= 2 || (looks >= 1 && articleEmpty) }

    var body: some View {
        let colours = Self.palette(looks)
        let faces = Self.fonts(looks)
        if !colours.isEmpty || !faces.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                HStack(alignment: .firstTextBaseline) {
                    SectionLabel(Copy.Pages.brand(looks: looks.count))
                    Spacer(minLength: 0)
                    TextButton(title: Copy.Pages.copyTokens, inline: true) {
                        AppPasteboard.copy(Self.tokens(looks))
                        store.toast = Copy.Pages.tokensCopied
                    }
                }
                if !colours.isEmpty {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(96)),
                                                 spacing: CicadaTheme.spacingSM)],
                              alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        ForEach(colours, id: \.self) { hex in
                            VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
                                CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                                    .fill(LooksColour.color(hex))
                                    .frame(height: CicadaTheme.scaled(44))
                                    .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                                // DR-19: copyable by selection, in SF with even digits — as the Looks page draws hex.
                                Text(hex.uppercased())
                                    .font(CicadaTheme.metaFont)
                                    .monospacedDigit()
                                    .foregroundStyle(CicadaTheme.textSecondary)
                                    .textSelection(.enabled)
                            }
                        }
                    }
                }
                if !faces.isEmpty {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        ForEach(faces, id: \.self) { face in
                            VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
                                // G137 R-M3: no face but the theme's. The look's family is named under the sample;
                                // the sample is the Looks page's stand-in (`LooksSpecimenGlyph`), never a custom font.
                                Text(Copy.Pages.typeSample)
                                    .font(CicadaTheme.font(size: 30, design: LooksSpecimenFace.design(nil)))
                                    .foregroundStyle(CicadaTheme.textPrimary)
                                Text(face).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                                    .textSelection(.enabled)
                            }
                            .padding(CicadaTheme.spacingMD)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgOption))
                            .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
