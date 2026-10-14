import SwiftUI

/// "Where this comes from" (owner 2026-10-14, G61): one place on a page that says where Cicada's knowledge about it
/// comes from and how fresh it is. Three parts, in the order a person checks them:
///
/// 1. two lines — how many beliefs have a place to check them, when the page was last said and its sources last
///    checked (DR-58: computed when read);
/// 2. **Sources and links** — the sources (G61's rows, with the beliefs each fact's sources back, each a way into that
///    belief's timeline), then the links the page's conversations named, each with the conversation it came from, and
///    the add field (`LookItUpSection`);
/// 3. **Conversations** — one row per app (mark, name, how many, what they back, when last), then the conversations
///    themselves with their best sentence (`WhereThisCameFromSection`).
///
/// Everything it draws comes from `GET /entities/{id}/sources/overview` and `/provenance`; it never reads the claims
/// list (an owner-sized page's is megabytes). It fetches nothing from the web: a site's mark is the page's own icon
/// route, which answers only for a site the page trusts (G61 S3-b), else a monogram.
struct PageSourcesSection: View {
    let entityId: String
    let entityType: EntityType?
    let overview: PageSourcesOverview?
    /// The sources are known (from the overview, or `/sources` on an older backend).
    let sourcesLoaded: Bool
    @Binding var sources: [EntitySource]
    let provenance: ProvenanceSectionState
    var highlighted: String? = nil
    var navigate: (String) -> Void = { _ in }
    var isCurrent: () -> Bool = { true }
    var onOpenFact: (PageSourceFact) -> Void = { _ in }
    var onChanged: () -> Void = {}

    @Environment(ProvenanceRouter.self) private var router: ProvenanceRouter?
    @Environment(ProvenanceCache.self) private var provenanceCache: ProvenanceCache?
    /// G198 — "Who wrote it", read when this section shows (`/blame`, not a Store domain).
    @State private var blame: PageBlame?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingCard) {
            if let overview, let lines = Self.lines(overview) {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    ForEach(lines, id: \.self) { Text($0) }
                }
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            }
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                SectionLabel(Copy.PageSources.sitesAndLinks)
                if sourcesLoaded {
                    // `.id` — the add field's draft belongs to one page.
                    LookItUpSection(entityId: entityId, entityType: entityType, sources: $sources,
                                    navigate: navigate, isCurrent: isCurrent, overview: overview,
                                    highlighted: highlighted, onOpenFact: onOpenFact,
                                    onOpenLinkOrigin: router == nil ? nil : openOrigin, onChanged: onChanged)
                        .id(entityId)
                } else {
                    SectionLoading(text: Copy.Graph.readingSources)
                }
            }
            if showsConversations {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    SectionLabel(Copy.PageSources.conversationsLabel)
                    if let apps = overview?.conversations.apps, !apps.isEmpty {
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(apps) { PageSourceAppRow(app: $0) }
                        }
                        .padding(.horizontal, -CicadaTheme.scaled(10))
                    }
                    // The apps above already say how many and where: the section's own sentence would repeat them.
                    WhereThisCameFromSection(entityId: entityId, state: provenance,
                                             showsConversationsSentence: overview == nil)
                }
            }
            // G198 — who last changed each part of the page's text, when and why (left out until it has something).
            if WhoWroteItSection.shows(blame), let blame {
                WhoWroteItSection(blame: blame).id(entityId)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .task(id: entityId) { await loadBlame() }
    }

    private func loadBlame() async {
        guard let provenanceCache else { return }
        blame = provenanceCache.cachedBlame(entityId: entityId)
        // The backend answers `pending` while its blame runs (G198 review B3): keep what is held and ask again, a few
        // times, a moment apart. The task ends when the section goes away.
        for attempt in 0..<CicadaTiming.blamePendingTries {
            switch await provenanceCache.blame(entityId: entityId) {
            case let .loaded(value) where value.pending:
                guard attempt + 1 < CicadaTiming.blamePendingTries else { return }
                try? await Task.sleep(for: .seconds(CicadaTiming.blamePendingRetry))
                if Task.isCancelled { return }
                continue
            case let .loaded(value): blame = value
            case .gone: blame = nil
            case .failed: break   // the last answer held stays (never blank)
            }
            return
        }
    }

    /// The opening lines: coverage, then freshness. Nil when there is nothing to say yet.
    static func lines(_ o: PageSourcesOverview) -> [String]? {
        let lines = [PageSourcesWords.coverage(o), PageSourcesWords.freshness(o)].compactMap { $0 }
        if lines.isEmpty, o.sources.isEmpty, o.links.isEmpty, o.conversations.total == 0 {
            return [Copy.PageSources.nothingYet]
        }
        return lines.isEmpty ? nil : lines
    }

    private var showsConversations: Bool {
        if let overview, overview.conversations.total > 0 { return true }
        switch provenance {
        case .unavailable: return false
        case let .loaded(p): return p.totals.conversations > 0 || !p.conversations.isEmpty
        default: return overview == nil
        }
    }

    private func openOrigin(_ origin: PageLinkOrigin) {
        guard origin.available, let router else { return }
        let title = origin.title.isEmpty ? nil : origin.title
        let target = origin.evidence.flatMap { ReaderTarget.evidence($0, subjectId: entityId, knownTitle: title) }
            ?? ReaderTarget(episode: origin.episode, focus: .mention(entityId: entityId), subjectId: entityId,
                            knownTitle: title, knownHarness: origin.harness)
        router.open(target)
    }
}

/// One app's conversations: its real mark (DR-52), its name, then how many, what they back and when last (one line).
private struct PageSourceAppRow: View {
    let app: PageSourceApp

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(10)) {
            OriginMark(origin: ReaderHeader.markOrigin(harness: app.harness, origin: app.origin),
                       size: CicadaTheme.scaled(14))
            Text(PageSourcesWords.appName(app))
                .font(CicadaTheme.rowFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
            Text(PageSourcesWords.appDetail(app))
                .font(CicadaTheme.metaFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .frame(minHeight: CicadaTheme.scaled(28))
        .accessibilityElement(children: .combine)
    }
}

/// The beliefs one fact's sources back, under that fact's rows: each a way into its own timeline; past four, how many
/// more (every one is in "What Cicada believes").
struct BackedFacts: View {
    let source: PageSource
    let onOpen: (PageSourceFact) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(source.facts) { fact in BackedFactRow(fact: fact) { onOpen(fact) } }
            if let more = PageSourcesWords.moreFacts(source) {
                Text(more)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.leading, BackedFactRow.indent)
                    .padding(.top, CicadaTheme.scaled(2))
            }
        }
    }
}

private struct BackedFactRow: View {
    /// Under the row's text, past its 20 pt mark (`FactSourceRow`).
    static var indent: CGFloat { CicadaTheme.scaled(40) }

    let fact: PageSourceFact
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: open) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Text(renderWikilinks(fact.text))
                    .font(CicadaTheme.font(size: 12))
                    .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Image(systemName: "clock")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .opacity(hovering ? 1 : 0)
                    .accessibilityHidden(true)
            }
            .padding(.leading, Self.indent)
            .padding(.trailing, CicadaTheme.spacingSM)
            .padding(.vertical, CicadaTheme.scaled(3))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(hovering ? CicadaTheme.bgHover : .clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(Copy.PageSources.openBelief)
        .accessibilityHint(Copy.PageSources.openBelief)
    }
}

/// A link the page's conversations named: its mark (the page's own icon route answers only for a site it trusts; else
/// a monogram), its title (else its host) in `accentText` (DR-6), the full URL, the line's note, then the conversation that named it —
/// mark, app, title, day (DR-54) — which opens in the Reader. ↗ opens the link; the menu keeps it as a source.
/// Owner rulings 2026-10-14: the URL line carries the date of what Cicada knows of the page ("Read Oct 2"), and a
/// short hover opens the link's bookmark card (`CicadaMotion.linkPreviewOpenDelay`) — never inline in the row
/// (DR-34/37).
struct PageLinkRow: View {
    let link: PageLink
    let entityId: String
    let onOpenOrigin: (() -> Void)?
    let onUseAsSource: () -> Void
    @State private var hovering = false
    @State private var previewing = false
    @State private var hoverTask: Task<Void, Never>?

    private var fact: LinkFact { LinkFactsCache.shared.fact(link.url, on: entityId) }

    private var urlLine: String {
        LinkCardModel.dateLine(fact).map { "\(link.url) · \($0)" } ?? link.url
    }

    private func hover(_ inside: Bool) {
        hovering = inside
        hoverTask?.cancel()
        let delay = inside ? CicadaMotion.linkPreviewOpenDelay : CicadaMotion.linkPreviewCloseDelay
        hoverTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            guard !Task.isCancelled else { return }
            previewing = inside && link.link != nil
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.scaled(10)) {
            mark
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(PageSourcesWords.linkTitle(link))
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.accentText)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .help(link.url)
                Text(urlLine)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .help(link.url)
                if let note = PageSourcesWords.linkNote(link) {
                    Text(note)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                }
                if let origin = link.cameFrom {
                    Button { onOpenOrigin?() } label: {
                        HStack(spacing: CicadaTheme.spacingXS) {
                            OriginMark(origin: ReaderHeader.markOrigin(harness: origin.harness, origin: origin.origin),
                                       size: CicadaTheme.scaled(12))
                            Text(PageSourcesWords.cameFrom(origin)).lineLimit(1)
                        }
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.cicadaPlain)
                    .disabled(onOpenOrigin == nil || !origin.available)
                    .help(Copy.PageSources.openConversation)
                }
            }
            Spacer(minLength: 0)
            if let url = link.link {
                IconButton(systemName: "arrow.up.right", help: Copy.PageSources.openLink(link.url)) {
                    NSWorkspace.shared.open(url)
                }
            }
            Menu {
                Button(Copy.PageSources.useAsSource, action: onUseAsSource)
            } label: {
                Image(systemName: "ellipsis")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                    .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
            .help(Copy.PageSources.linkMenu)
            .accessibilityLabel(Copy.PageSources.linkMenu)
        }
        .padding(.leading, CicadaTheme.scaled(10))
        .padding(.trailing, CicadaTheme.spacingXS)
        .padding(.vertical, CicadaTheme.scaled(6))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(hovering ? CicadaTheme.bgHover : Color.clear))
        .onHover { hover($0) }
        .onDisappear { hoverTask?.cancel() }
        .popover(isPresented: $previewing, arrowEdge: .leading) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                BookmarkCard(fact: fact, entityId: entityId)
                Text(Copy.Links.openHint)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .padding(CicadaTheme.spacingMD)
            .frame(width: 380)
        }
    }

    @ViewBuilder
    private var mark: some View {
        if let site = link.site, !site.isEmpty {
            SiteIcon(site: site, label: link.title.isEmpty ? nil : link.title, size: .inline, entity: entityId)
                .padding(.top, CicadaTheme.scaled(2))
        } else {
            Image(systemName: "link")
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(.top, CicadaTheme.scaled(3))
                .accessibilityHidden(true)
        }
    }
}

/// The way back from a belief to where to check it (owner 2026-10-14): beside its evidence chip, the best source for
/// its fact — the site's mark and name — which opens "Where this comes from" on that source. Styled as the evidence
/// chip it sits beside; it never says the source was checked (S3 is shadow).
struct LookUpChip: View {
    let source: PageSource
    let entityId: String
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: open) {
            HStack(spacing: 4) {
                if let site = source.site, !site.isEmpty {
                    SiteIcon(site: site, size: .inline, entity: entityId)
                } else {
                    Image(systemName: source.source.kind == "note" ? "text.quote" : "doc")
                        .font(CicadaTheme.font(size: 9, weight: .medium))
                        .accessibilityHidden(true)
                }
                Text(PageSourcesWords.lookUpChip(source))
                    .font(CicadaTheme.font(size: 10, weight: .regular))
                    .lineLimit(1)
            }
            .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(CicadaTheme.surfaceHover.opacity(0.6))
            .clipShape(Capsule())
            .contentShape(Capsule())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(Copy.PageSources.lookUpHelp(source.source.ref))
        .accessibilityLabel(PageSourcesWords.lookUpChip(source))
    }
}
