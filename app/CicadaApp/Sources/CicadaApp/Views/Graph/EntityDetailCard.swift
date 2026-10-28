import SwiftUI
import UniformTypeIdentifiers

// MARK: - EntityCardNavigation
//
// Bug 3 / G108 — the entity-card "go deeper, then come back" stack. By
// default `EntityDetailCard` reads/drives `GraphViewModel`'s own history
// (the graph tab's floating card). A host that shows this card OUTSIDE that
// context — the Clusters/Topics detail page, which keeps its own local
// selection rather than sharing `graphVM.selectedEntity` — supplies its own
// `EntityCardNavigation` so "go deeper" stays scoped to that presentation
// instead of silently hijacking the graph tab's card. Either way, the actual
// push/pop/reset logic is the SAME pure `EntityNavigationStack` type.
struct EntityCardNavigation {
    let canGoBack: Bool
    let backTargetName: String?
    let goBack: () -> Void
    /// Navigate deeper to `id` — a wikilink tap, a transclusion click, a
    /// claim citation.
    let navigate: (String) -> Void
}

struct EntityDetailCard: View {
    /// G133 — should the card ask `GET /entities/{id}/paper`? Any `media`
    /// entity whose kind is unknown (the graph-node stub carries no `media`
    /// block) or known to be a paper. Only a media block that says it is NOT
    /// a paper skips the call. Pure so the stub case is pinned by a test
    /// (task 7 review r1: the stub never fetched, so a first open showed no
    /// paper card and — with the `!isPaper` preview guard — no preview).
    static func wantsPaperDetail(type: EntityType, media: MediaBlock?) -> Bool {
        guard type == .media else { return false }
        return media?.isPaper ?? true
    }

    let entity: Entity
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    /// `nil` (the default) means "use `graphVM`'s own history" — see
    /// `EntityCardNavigation` above.
    let navigation: EntityCardNavigation?
    @State private var selectedTab: EntityCardTab = .content
    @State private var showRawMarkdown: Bool

    // Claim-layer state (§3b perspectives, §4 timeline). Loaded lazily on tab
    // open. Includes superseded claims so the timeline tab can list contested
    // keys; the perspective tab filters to valid claims itself.
    @State private var claims: [Claim] = []
    @State private var claimsLoaded = false
    /// F4 — the verbatim file, fetched for Source or Copy when the card's payload withheld its fence (`rawOmitted`).
    @State private var rawFile = RawFileLoader()
    /// What every tab shows from `claims`, derived once per load off the main actor (`ClaimDigest`).
    @State private var digest = ClaimDigest.empty
    /// R-DG23 — the Timeline tab's open rows, and the one a belief's clock asked for.
    @State private var expandedKeys: Set<BeliefKey> = []
    @State private var requestedKey: BeliefKey?

    // Location listing (issue #7). Loaded lazily on appear for `.location`
    // entities; nil while loading or when no path/endpoint is available.
    @State private var locationListing: LocationListing?

    // Repository context (G9 companion). Loaded lazily on appear for
    // `.project`/`.directory` entities; empty while loading, on 404, or when
    // the entity carries no `repos:` key — the section renders nothing in
    // all three cases (see `RepoCard.load`).
    @State private var repoContexts: [RepoContext] = []

    /// G133 — a paper page's two tiers, fetched once per open.
    @State private var paperDetail: PaperDetail?
    /// A picture held over the page (owner 2026-10-20: dropping one adds it to the page's looks).
    @State private var lookDropTargeted = false
    /// Ruling 48 (17), DR-81 — nothing on the page folds. Adding a link or a look starts from the page's menu
    /// (`pageMenu`) when the page has none yet, so an empty section is never drawn waiting for one.
    @State private var addingLink = false
    @State private var addingLook = false
    /// `/provenance` was asked for this page: the History, Perspectives and Timeline tabs read it when opened — the
    /// Content tab never does (ruling 48: a card open is one request).
    @State private var provenanceAskedFor: String?
    /// The full page could not be read: the card says so, with a retry, instead of "Reading the page…" forever (DR-32).
    @State private var pageReadFailed = false
    /// The one claims read in flight for this card: the beliefs section and the Perspectives or Timeline tab opening
    /// together share it rather than each asking for megabytes.
    @State private var claimsRead: Task<Void, Never>?

    // History tab (G68 §2.10). `entity.history` is empty BOTH before the full
    // entity body has landed and when the page has no commits, so track the
    // fetch explicitly rather than inferring from an empty array.
    @State private var fetchedHistory: [EntityHistoryEntry]?
    @State private var historyLoading = false
    /// Set when `fetchEntityHistory` throws, cleared at the start of every
    /// attempt. Kept separate from `fetchedHistory` so a failure is never
    /// mistaken for "fetched successfully, and it was empty" (see
    /// `HistoryTabState.error`).
    @State private var historyLoadFailed = false
    /// #244 — changes older than the served window, read a page at a time by "Older changes".
    @State private var olderHistory: [EntityHistoryEntry] = []
    @State private var historyPaging: HistoryPaging?
    @State private var olderLoading = false
    @State private var olderFailed = false

    /// G66 — the decay class the user just picked, shown immediately while the
    /// PUT is in flight. Cleared once the reload lands (or on failure, so the
    /// chip snaps back to the server's truth).
    @State private var pendingDecayClass: DecayClass?

    /// G118 slice 2 — "Where this came from" (§4.5), one `/provenance` call per
    /// card, cached in memory by `ProvenanceCache` (never a Store domain,
    /// R-PB11). Loaded at the card level, not the Content tab's, because the
    /// same payload names the agent on every evidence chip in Perspectives and
    /// Timeline (`evidenceDocIndex`) and maps a history row's conversation to
    /// an episode the Reader can open.
    @State private var provenanceState: ProvenanceSectionState = .loading
    @Environment(ProvenanceCache.self) private var provenanceCache: ProvenanceCache?
    @Environment(ProvenanceRouter.self) private var provenanceRouter: ProvenanceRouter?

    // G67 — per-commit diffs in the History tab, fetched on demand and cached
    // per (entity, commit) — `DiffCacheKey`, not commit hash alone: one
    // Sleep-cycle commit routinely touches several entity files, so the same
    // hash commonly appears in more than one entity's history, and keying by
    // hash alone let entity B render entity A's cached diff for a shared
    // commit (fix round 1). `expanded` is the set of commits the user has
    // opened; `loading` guards against a second fetch while the first is in
    // flight; `diffErrors` marks a fetch that failed so the row can offer a
    // retry instead of silently reading as "no changes".
    //
    // `activeEntityId` names which entity these caches currently belong to.
    // `toggleCommit`'s fetch `Task` is a bare, uncancelled task: if the user
    // swaps entities while it's in flight, it resolves *after* the manual
    // reset below and would otherwise still write into the (now-current)
    // dicts. The `DiffCacheKey` already prevents that write from being
    // *read* under the wrong entity, but the `activeEntityId` guard in
    // `fetchDiff` additionally stops the stale write from happening at all.
    @State private var activeEntityId: String = ""
    @State private var expandedCommits: Set<DiffCacheKey> = []
    @State private var commitDiffs: [DiffCacheKey: EntityDiff] = [:]
    @State private var loadingCommits: Set<DiffCacheKey> = []
    @State private var diffErrors: Set<DiffCacheKey> = []

    private func diffKey(_ commitHash: String) -> DiffCacheKey {
        DiffCacheKey(entityId: entity.id, commitHash: commitHash)
    }

    /// Whether to show the card's own close (✕) button. The Clusters detail
    /// embeds this card inside a view that already provides a Back button, so
    /// it passes `false` — the card's ✕ only drives `graphVM.clearSelection()`,
    /// which is a no-op (dead button) outside the graph's selection context.
    let showsCloseButton: Bool
    /// R-DG13 — `.column` on the Graph, `.card` in Clusters (its detail column frames the card, R-DL10).
    let style: EntityCardStyle
    /// The column's × — the page closes the column and its Reader together (R-DG7). Nil: `clearSelection()`.
    let onClose: (() -> Void)?
    /// DR-28 — the page decides what Esc closes (the Reader first). Clusters passes its own Esc order, so Esc there
    /// no longer clears the Graph's selection behind it. Nil: Esc does nothing here.
    let onEscape: (() -> Void)?

    /// `defaultRaw` opens the card on the verbatim Source view — used by the
    /// graph's click-to-preview overlay so a node tap shows raw markdown first.
    init(
        entity: Entity, defaultRaw: Bool = false, showsCloseButton: Bool = true,
        navigation: EntityCardNavigation? = nil, style: EntityCardStyle = .card,
        onClose: (() -> Void)? = nil, onEscape: (() -> Void)? = nil
    ) {
        self.entity = entity
        self.showsCloseButton = showsCloseButton
        self.navigation = navigation
        self.style = style
        self.onClose = onClose
        self.onEscape = onEscape
        _showRawMarkdown = State(initialValue: defaultRaw)
    }

    // MARK: - Navigation (bug 3 / G108)

    private var canGoBack: Bool { navigation?.canGoBack ?? graphVM.canGoBack }
    private var backTargetName: String? { navigation?.backTargetName ?? graphVM.backTargetName }

    private func goBack() {
        if let navigation { navigation.goBack() } else { graphVM.goBackEntity() }
    }

    /// Every wikilink/transclusion/claim-citation tap inside this card routes
    /// here via `.wikilinkNavigation` below.
    private func navigate(to id: String) {
        if let navigation { navigation.navigate(id) } else { graphVM.pushEntity(id: id) }
    }

    private var isStub: Bool { entity.isStub }

    /// F-12's graph glyph — the Graph tab, with this node revealed (the Reader's "Show on graph" path).
    private func showOnGraph() {
        router.pendingTab = .graph
        graphVM.revealEntity(id: entity.id)
    }

    private func close() {
        if let onClose { onClose() } else { graphVM.clearSelection() }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            EntityCardHeader(
                entity: entity,
                summary: EntityHeaderWords.summary(markdown: entity.markdownContent, isStub: isStub),
                isStub: isStub,
                canGoBack: canGoBack, backTargetName: backTargetName, onBack: goBack,
                showsClose: showsCloseButton, onClose: close,
                tabs: EntityTabs.tabs(digest: claimsLoaded ? digest : nil,
                                      historyCount: EntityTabs.historyCount(embedded: entity.history, fetched: fetchedHistory),
                                      selected: selectedTab),
                selection: $selectedTab,
                inset: style.inset,
                pictureInputs: entity.pictureInputs,
                onShowOnGraph: style == .card ? showOnGraph : nil,
                pageMenu: isStub ? nil : AnyView(pageMenu),
                onOpenEntity: { navigate(to: $0) },
                showsSource: $showRawMarkdown, onCopy: copyMarkdown)
            ScrollViewReader { _ in
                ScrollView {
                    switch selectedTab {
                    case .content: contentTab
                    case .perspectives: perspectivesTab
                    case .history: historyTab
                    case .timeline: timelineTab
                    }
                }
            }
        }
        .frame(maxHeight: .infinity)
        .modifier(EntityCardChrome(style: style))
        // R-DG11 — focus inside the column still reaches the page's Esc order.
        .focusable()
        .focusEffectDisabled()
        .onExitCommand { onEscape?() }
        // R-DG16 — a tab loads what it shows; the counts were loaded when the column opened.
        .onChange(of: selectedTab) { _, tab in
            switch tab {
            case .history:
                Task { await loadHistoryIfNeeded() }
                Task { await loadProvenanceIfNeeded() }
            case .perspectives, .timeline:
                Task { await loadClaimsIfNeeded() }
                Task { await loadProvenanceIfNeeded() }
            case .content: break
            }
        }
        // Installed ONCE here — see `View.wikilinkNavigation` in MarkdownBody.swift. Covers the header's Summary,
        // the rendered body, transcluded embeds, and every claim chip in Perspectives and the inline Timeline.
        // The Belief Timeline sheet (and its step-aside for the Reader) retired with R-DG23.
        .wikilinkNavigation(onSelect: navigate)
        // Outermost on purpose: every evidence chip in the tabs reads it.
        .environment(\.evidenceDocIndex, EvidenceDocIndex.from(provenanceState.value))
        // Ruling 48 — a card open is one request (`GET /entities/{id}` with its blocks). `/provenance` names the agent on
        // every evidence chip and maps a history row to its conversation: the tabs that draw those read it when opened.
        .onChange(of: entity.id) { _, _ in
            provenanceAskedFor = nil
            provenanceState = .loading
            if selectedTab != .content { Task { await loadProvenanceIfNeeded() } }
        }
    }

    /// `/provenance` once per page, for the tabs that draw evidence chips and history rows.
    private func loadProvenanceIfNeeded() async {
        guard provenanceAskedFor != entity.id else { return }
        provenanceAskedFor = entity.id
        await loadProvenance()
    }

    /// One `/provenance` per entity (ETag-revalidated by the cache). A 404 —
    /// an older backend — hides the section rather than showing an error.
    private func loadProvenance() async {
        guard let provenanceCache else {
            provenanceState = .unavailable
            return
        }
        provenanceState = .loading
        let result = await provenanceCache.provenance(entityId: entity.id)
        // A card swapped to another entity cancels this task; a late answer
        // for the old one must not land under the new name.
        guard !Task.isCancelled else { return }
        provenanceState = ProvenanceSectionState(result)
    }

    // MARK: - Content Tab

    /// What the page holds (`GET /entities/{id}`'s `blocks`); nil on a graph stub or from an older backend.
    private var blocks: PageBlocks? { isStub ? nil : entity.blocks }

    /// Ruling 48 (7) — the brand leads when looks are what the page is about.
    private var brandLeads: Bool {
        PageBrandBlock.leads(looks: blocks?.looks.count ?? 0,
                             articleEmpty: WikiArticleCache.shared.article(articleKey).isEmpty)
    }

    /// Where to check is drawn when it holds something, or while the person is adding the page's first link (DR-81).
    private var showsWhereToCheck: Bool {
        !PageWords.rows(blocks?.sources).isEmpty || PageWords.proposals(blocks?.sources) > 0 || addingLink
    }

    /// Ruling 48 (2026-10-28; DR-78…DR-81) — the page reads top to bottom in the server's order, the same for every
    /// type: In short, Where to check, the type block, Ongoing, the article carrying its beliefs, References. Nothing
    /// folds; a block with nothing in it is not drawn. Capped at DR-36's 760.
    private var contentTab: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingCard) {
            // Ruling 48 (1), (2) — the page's own open question, one at a time ("1 of N"); nothing when it has none.
            PageQuestionsStrip(entityId: entity.id).id(entity.id)
            if !isStub, !showRawMarkdown {
                PageInShort(relevance: blocks?.relevance ?? entity.relevance)
                if showsWhereToCheck {
                    WhereToCheckBox(entityId: entity.id, isPerson: entity.type == .person, sources: blocks?.sources,
                                    adding: $addingLink, onChanged: reloadPage,
                                    isCurrent: { [id = entity.id] in activeEntityId == id })
                        .id(entity.id)
                }
                if brandLeads {
                    PageBrandBlock(looks: blocks?.looks ?? [])
                    looksSection
                }
            }
            if Self.listsFolder(entity.type) { locationSection }
            if !repoContexts.isEmpty { repositorySection }
            if !isStub, !showRawMarkdown, let blocks {
                PageOngoing(items: blocks.ongoing, total: blocks.ongoingTotal)
            }
            if !pageBlockIsEmpty { pageBlock }
            if !isStub, !showRawMarkdown, let cites = blocks?.citations, !cites.beliefs.isEmpty {
                PageBeliefSentences(entityId: entity.id, beliefs: cites.beliefs, total: cites.beliefsTotal,
                                    onMore: { selectedTab = .perspectives })
            }
            if !isStub, !showRawMarkdown, !(blocks?.looks.isEmpty ?? true), !brandLeads { looksSection }
            if !isStub, !showRawMarkdown, let cites = blocks?.citations {
                PageReferences(citations: cites) { selectedTab = .history }
            }
        }
        .frame(maxWidth: CicadaTheme.scaled(760), alignment: .leading)
        .modifier(EntityTabInsets(style: style))
        // Owner 2026-10-20 — a picture dropped anywhere on a page becomes one of its looks (the app reads the picture,
        // the backend is handed bytes). The ring says where it will land while it is held over the page (DR-9).
        .overlay {
            if lookDropTargeted {
                CicadaTheme.shape(CicadaTheme.radiusLarge)
                    .strokeBorder(CicadaTheme.borderLight, style: StrokeStyle(lineWidth: 2, dash: [6, 4]))
                    .allowsHitTesting(false)
            }
        }
        .onDrop(of: [.image, .fileURL], isTargeted: $lookDropTargeted) { providers in
            guard !isStub else { return false }
            let id = entity.id
            LooksIntake.load(providers) { image in
                Task { store.toast = await PageLooks.drop(image, on: id) }
            }
            return true
        }
        .task(id: entity.id) {
            // G124 R11 — a card open is a read. Fire-and-forget on its own
            // Task so a slow ledger never delays the page below.
            Task { await APIClient.shared.recordEntityRead(id: entity.id) }
            // Reset before (re)fetching so swapping between entities can't show
            // a previous entity's location/repo data. `.task(id:)`
            // already guarantees this runs once per id, so no extra "loaded"
            // guard is needed.
            locationListing = nil
            repoContexts = []
            pageReadFailed = false
            paperDetail = nil
            pendingDecayClass = nil
            activeEntityId = entity.id
            addingLink = false
            addingLook = false
            CitationDetailCache.shared.forget(entity.id)
            expandedCommits = []
            commitDiffs = [:]
            loadingCommits = []
            diffErrors = []
            rawFile = RawFileLoader()
            olderHistory = []
            historyPaging = nil
            olderFailed = false
            // §5.7 — the card opened on the graph-node stub, whose `markdownContent` is the server's short `summary`
            // (already rendered above, so there is never an empty card). Upgrade it to the full entity through the
            // Store's memoised cache; the swap lands via `graphVM.selectedEntity`/`entities`, which is what feeds
            // this view its `entity`. Its `blocks` carry every block the page draws (ruling 48: one request).
            let pageRead = await graphVM.loadFullEntity(id: entity.id)
            if !pageRead, !Task.isCancelled { pageReadFailed = true }
            // Gated on what the graph-node STUB already knows (task 7 review
            // r1): the card opens on a stub whose `media` is nil, and the
            // full-entity swap below keeps the same `.task(id:)`, so a check
            // on `media?.isPaper` alone never fired on a first open. The
            // endpoint 404s for a non-paper, which `try?` reads as nil.
            if Self.wantsPaperDetail(type: entity.type, media: entity.media) {
                paperDetail = try? await APIClient.shared.fetchPaperDetail(id: entity.id)
            }
            // Location and directory pages declare a folder. The backend names the path only;
            // the app lists it, so any macOS prompt names Cicada (the ~/Library rail).
            if Self.listsFolder(entity.type) {
                let declared = (try? await APIClient.shared.fetchLocationListing(id: entity.id))?.path ?? entity.path
                if let declared, !declared.isEmpty {
                    let listing = await LocationLister.list(declared)
                    if !Task.isCancelled { locationListing = listing }
                }
            }
            // Only project/directory entities carry a `repos:` frontmatter key. The backend names the repos;
            // the app runs git in the ones on this Mac (so a prompt names Cicada) and posts what it printed.
            if entity.type == .project || entity.type == .directory {
                let contexts = await RepoCard.load(entityId: entity.id)
                if !Task.isCancelled { repoContexts = contexts }
            }
        }
    }

    /// The page again, after a write on it (a link added, taken or removed): its blocks are the server's answer.
    private func reloadPage() {
        let id = entity.id
        Task { await graphVM.reloadEntity(id: id) }
    }

    /// The page's looks as tiles (`PageLooksSection`) — drawn only when the page holds one (`blocks.looks`), so a
    /// page with none reads nothing more on open.
    private var looksSection: some View {
        PageLooksSection(entityId: entity.id, navigate: { navigate(to: $0) })
    }

    /// The page's menu (DR-81: what used to wait in the Details fold): add a link or a look, and how the page fades —
    /// the person's authority over how fast Cicada forgets (G66).
    private var pageMenu: some View {
        Menu {
            Button(Copy.Pages.addLink) { addingLink = true }
            Button(Copy.Pages.addLook) { addingLook = true }
            Divider()
            Menu("\(Copy.Pages.fades): \(fadesLabel)") {
                ForEach(DecayClass.allCases) { option in
                    Button { setDecay(option) } label: {
                        Label("\(DetailsWords.fades(option)) — \(option.blurb)",
                              systemImage: option == shownDecayClass ? "checkmark" : option.icon)
                    }
                }
            }
        } label: {
            Image(systemName: "ellipsis")
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(CicadaTheme.textSecondary)
                .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
                .contentShape(Rectangle())
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .help(Copy.Pages.more)
        .accessibilityLabel(Copy.Pages.more)
        .popover(isPresented: $addingLook, arrowEdge: .bottom) {
            PageLookAdd(entityId: entity.id, unplaced: LooksCache.shared.unplaced)
                .padding(CicadaTheme.spacingMD)
                .frame(width: CicadaTheme.scaled(360), alignment: .leading)
        }
    }

    /// The page: a paper's or a media page's own card, then the article (or the file). Its Rendered/Source switch
    /// and Copy sit at the end of the header's tab row (`EntityCardHeader.pageTools`).
    private var pageBlock: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            // G133: a paper leads with why it is in memory, then the dated abstract — and never loads
            // arxiv.org in a preview (R-LS19).
            if let paperDetail {
                PaperCard(detail: paperDetail)
            } else if entity.type == .media, let media = entity.media, media.hasURL, !media.isPaper {
                // G11: rich media preview above the body for `media`-type entities.
                MediaPreview(model: MediaPreviewModel(block: media, title: entity.name, description: mediaDescription))
                if VideoBlock.isVideo(media) {
                    // G162 (M6) — the entity card's media block carries what Cicada holds for a video, joined by
                    // the page and its link (a media entity id alone is not unique).
                    VideoBlock(feedId: entity.id + "|" + media.url, url: media.url, title: entity.name,
                               mediaEntityId: entity.id)
                }
            }
            if showRawMarkdown { rawMarkdownView } else { renderedMarkdownView }
        }
    }

    private func retryPageRead() {
        let id = entity.id
        pageReadFailed = false
        Task {
            let read = await graphVM.loadFullEntity(id: id)
            if !read, id == entity.id { pageReadFailed = true }
        }
    }

    // MARK: - Location Section (issue #7)
    //
    // For `.location` and `.directory` entities, shows the declared directory path
    // (monospace, copyable) and a bounded listing of its immediate children, read by
    // `LocationLister` on this Mac. Degrades quietly: no path → renders nothing; a
    // folder macOS will not let Cicada read says where to allow it.

    /// The page types that declare a folder (G18: `directory`; `location` for legacy graphs).
    static func listsFolder(_ type: EntityType) -> Bool {
        type == .location || type == .directory
    }

    @ViewBuilder
    private var locationSection: some View {
        // Prefer the listing's path (authoritative), falling back to the
        // entity's own `path` field if surfaced on the EntityResponse.
        let path = locationListing?.path ?? entity.path
        if let path, !path.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                HStack {
                    SectionLabel(Copy.Graph.folder)
                    Spacer(minLength: 0)
                    IconButton(systemName: "doc.on.doc", help: Copy.Graph.copyPath) { copyPath(path) }
                }

                Text(path)
                    .font(CicadaTheme.monoFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .textSelection(.enabled)
                    .lineLimit(2)
                    .truncationMode(.middle)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(CicadaTheme.spacingSM)
                    .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgFocus))
                    .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))

                locationContents
            }
        }
    }

    @ViewBuilder
    private var locationContents: some View {
        if let listing = locationListing {
            if !listing.exists {
                locationNote(Copy.Graph.folderNotFound, icon: "questionmark.folder")
            } else if !listing.accessible {
                locationNote(Copy.Graph.folderNotAllowed, icon: "lock")
            } else if listing.entries.isEmpty {
                locationNote(Copy.Graph.folderEmpty, icon: "tray")
            } else {
                VStack(alignment: .leading, spacing: 1) {
                    ForEach(listing.entries) { entry in
                        HStack(spacing: CicadaTheme.spacingSM) {
                            Image(systemName: entry.isDir ? "folder.fill" : "doc")
                                .font(CicadaTheme.font(size: 11))
                                .foregroundStyle(entry.isDir
                                                 ? CicadaTheme.entityColor(for: .location)
                                                 : CicadaTheme.textTertiary)
                                .frame(width: 16)
                            Text(entry.name)
                                .font(CicadaTheme.metaFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .lineLimit(1)
                            Spacer()
                            if !entry.isDir {
                                Text(humanSize(entry.size))
                                    .font(CicadaTheme.font(size: 10).monospacedDigit())
                                    .foregroundStyle(CicadaTheme.textTertiary)
                            }
                        }
                        .padding(.vertical, 2)
                    }
                    if listing.truncated {
                        Text(Copy.Graph.folderTruncated)
                            .font(CicadaTheme.font(size: 10))
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .padding(.top, 2)
                    }
                }
            }
        }
    }

    private func locationNote(_ text: String, icon: String) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Image(systemName: icon)
                .font(CicadaTheme.font(size: 11))
                .foregroundStyle(CicadaTheme.textTertiary)
            Text(text)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    /// Human-readable byte size (e.g. "12 KB"). Dirs pass 0 and aren't shown.
    private func humanSize(_ bytes: Int) -> String {
        let units = ["B", "KB", "MB", "GB", "TB"]
        var value = Double(bytes)
        var unit = 0
        while value >= 1024, unit < units.count - 1 {
            value /= 1024
            unit += 1
        }
        return unit == 0
            ? "\(bytes) \(units[unit])"
            : String(format: "%.1f %@", value, units[unit])
    }

    // MARK: - Repository Section (G9 companion)
    //
    // For `.project`/`.directory` entities carrying a `repos:` frontmatter
    // key, shows the local-checkout state per declared repo — remote,
    // branch, dirty/ahead/behind counts, last commit, worktrees, and any
    // `stale_hint` — as `RepoCard` loads it (git run by the app, parsed by the
    // backend). Gated entirely by `!repoContexts.isEmpty` in `contentTab`,
    // so this only ever renders once data has actually arrived — no empty
    // section, no loading skeleton.

    private var repositorySection: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(repoContexts.count > 1 ? Copy.Graph.repositories : Copy.Graph.repository)
            ForEach(repoContexts) { repoBlock($0) }
        }
    }

    /// G9 — git context as the app just saw it (`RepoCard`). R-DG21: words and neutral tags, one block on
    /// `bgFocus` with a resting ring (DR-7, DR-9). Paths, hashes and branches stay copyable (DR-19).
    private func repoBlock(_ repo: RepoContext) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Text(repo.remote?.isEmpty == false ? repo.remote! : repo.path)
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer(minLength: 0)
                Text(RepoWords.status(repo.status))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                IconButton(systemName: "doc.on.doc", help: Copy.Graph.copyPath) { copyPath(repo.path) }
            }
            Text(repo.path)
                .font(CicadaTheme.monoFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(1)
                .truncationMode(.middle)
                .textSelection(.enabled)
            let tags = RepoWords.tags(branch: repo.currentBranch, dirty: repo.dirtyFiles, ahead: repo.ahead, behind: repo.behind)
            if !tags.isEmpty {
                FlowLayout(spacing: 6) { ForEach(tags, id: \.self) { Tag(text: $0) } }
            }
            if let commit = repo.lastCommit, !commit.hash.isEmpty {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(commit.shortHash).font(CicadaTheme.monoFont).foregroundStyle(CicadaTheme.textTertiary)
                    Text(commit.subject).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                    Spacer(minLength: 0)
                    Text(relativeDate(commit.dateValue)).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            if repo.worktrees.count > 1 {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(repo.worktrees, id: \.path) { wt in
                        Text(wt.branch ?? wt.path)
                            .font(CicadaTheme.font(size: 11, design: .monospaced))
                            .foregroundStyle(wt.isMain ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                }
            }
            if let hint = repo.staleHint, !hint.isEmpty {
                Text(hint).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if let fix = RepoWords.fix(repo.status) {
                Text(fix).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
        .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
    }

    private func copyPath(_ p: String) {
        AppPasteboard.copy(p)
    }

    private func relativeDate(_ date: Date) -> String {
        let fmt = RelativeDateTimeFormatter()
        fmt.unitsStyle = .abbreviated
        return fmt.localizedString(for: date, relativeTo: .now)
    }

    /// The `## Description` body section of a media entity, used as the website
    /// preview card's description line. Falls back to `## Summary`. Returns nil
    /// when neither is present.
    private var mediaDescription: String? {
        EntityProse.firstSection(["## Description", "## Summary"], in: entity.markdownContent)
    }

    // The section readers live in `EntityProse` (F1 R-FX8): one copy of the
    // rule that strips the claims fence before any section is read.

    /// The page's article (`WikiArticle`): the prose without the sections that already have their own surface
    /// (`## Summary` → the header, R-DG15; `## Description` → the media card) or the claims fence (R-FX8). A stub's
    /// markdown IS the preview the header already shows, so it has none.
    private var articleKey: WikiArticleCache.Key {
        WikiArticleCache.Key(markdown: isStub ? "" : entity.markdownContent, dropping: WikiArticle.ownSurfaces)
    }

    /// Whether `pageBlock` would draw nothing: the rendered view of a loaded page with no paper or media card, no hero
    /// and no article (the first screen is built synchronously, so an empty one is known now, never a guess).
    private var pageBlockIsEmpty: Bool {
        guard !showRawMarkdown, !isStub, paperDetail == nil else { return false }
        if entity.type == .media, let media = entity.media, media.hasURL, !media.isPaper { return false }
        if HeroPreview.hasPreviewableAsset(for: entity) { return false }
        return WikiArticleCache.shared.article(articleKey).isEmpty
    }

    private var renderedMarkdownView: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            // G23/G25: prominent media/website/image hero, shown above
            // everything else — including the G24 summary — when the entity
            // carries a previewable asset. Gated here (rather than always
            // inserting `HeroPreview` and letting it self-collapse) so a
            // non-previewable entity doesn't even cost a layout slot.
            if HeroPreview.hasPreviewableAsset(for: entity) {
                HeroPreview(entity: entity)
            }
            if isStub, pageReadFailed {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(Copy.Graph.pageUnavailable)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    NeutralButton(title: Copy.Graph.retry) { retryPageRead() }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            } else if isStub {
                // The full page is on its way, said in words (it lands in well under a second); a failed read says so.
                SectionLoading(text: Copy.Graph.readingPage)
            } else {
                // DR-80 — the article carries the beliefs: each cited line ends with its sources' markers.
                WikiPageView(key: articleKey, entityId: isStub ? nil : entity.id, citations: blocks?.citations)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private var rawMarkdownView: some View {
        // Prefer the verbatim file from the API (transparency: this is the
        // exact markdown on disk, frontmatter included). The reconstruction
        // below only covers placeholder entities that haven't fully loaded.
        if entity.rawOmitted, rawFile.text == nil {
            if rawFile.failed {
                // Review r1 #5: a failed read is said, never replaced by a reconstruction shown as the file.
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(Copy.Graph.sourceUnavailable)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    NeutralButton(title: Copy.Graph.retry) { Task { await loadRaw() } }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                ProgressView().controlSize(.small)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .task(id: entity.id) { await loadRaw() }
            }
        } else {
            let shown = SourceText.shown(RawFile.verbatim(entity, fetched: rawFile.text) ?? buildFullMarkdown())
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Text(shown.text)
                    .font(CicadaTheme.monoFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if let folded = shown.foldedBytes {
                    Text(Copy.Graph.sourceFolded(bytes: folded))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(CicadaTheme.spacingMD)
            .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
            .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        }
    }

    /// F4 — the file the payload withheld, once per card; a failure stays a failure (Retry asks again).
    private func loadRaw() async {
        guard entity.rawOmitted else { return }
        await rawFile.load(entity.id) { try await APIClient.shared.fetchEntityRaw(id: $0) }
    }

    /// Copy takes the whole file. For a withheld file that is the fetched one or nothing — never a reconstruction,
    /// which would drop the claims fence and every frontmatter key it does not know (review r1 #5).
    private func copyMarkdown() {
        if let text = RawFile.verbatim(entity, fetched: rawFile.text) { return AppPasteboard.copy(text) }
        guard entity.rawOmitted else { return AppPasteboard.copy(buildFullMarkdown()) }
        Task {
            await loadRaw()
            if let text = RawFile.verbatim(entity, fetched: rawFile.text) {
                AppPasteboard.copy(text)
            } else {
                store.toast = Copy.Graph.copyFailed
            }
        }
    }

    // MARK: - Fades (G66 §1.7)
    //
    // The raw `decay_rate` number was never meaningful to a reader; the class is. The menu PUTs the override —
    // the person's authority over how fast the agent forgets.

    private var shownDecayClass: DecayClass { pendingDecayClass ?? entity.decayClass }

    /// G147 (R-FD10) — the value is the pace Sleep actually charges ("Slowly — mentioned across
    /// 12 weeks"), not only the class word; while an override is in flight it shows the chosen
    /// class's own words until the reload lands (the optimistic flip).
    private var fadesLabel: String {
        if let pendingDecayClass { return DetailsWords.fades(pendingDecayClass) }
        return FadeWords.detail(entity.decay, fallback: entity.decayClass)
    }

    private func setDecay(_ option: DecayClass) {
        guard option != entity.decayClass else { return }
        guard !store.refusesWriteWhileSwitching() else { return }   // G183(d): the page may be the other bank's
        let origin = store.bank
        pendingDecayClass = option  // optimistic: the chip flips immediately
        Task {
            do {
                _ = try await BankScope.bound(to: origin) {
                    try await APIClient.shared.setDecayClass(entityId: entity.id, option)
                }
                await graphVM.reloadEntity(id: entity.id)
            } catch {
                // Leave the server's value in place rather than lying about it, and say why (G177/G183: a 409 while
                // Sleep holds the pages names Sleep; the chip's siblings toast through the Store the same way).
                if !(SyncCancellation.isCancellation(error) || Task.isCancelled) {
                    store.toast = DecayChangeFailure.message(error)
                }
            }
            pendingDecayClass = nil
        }
    }

    // MARK: - History Tab

    // G68 §2.10 — three branches, resolved by `HistoryTabState`: a spinner while the fetch is in flight, an empty
    // state once it's confirmed there is nothing, and (the common case) the G67 diff-expansion list. Plain words,
    // no decorative glyph (DR-53); the retry is a neutral button (DR-40).
    @ViewBuilder
    private var historyTab: some View {
        switch historyState {
        case .loading:
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text(Copy.Graph.readingHistory)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .frame(maxWidth: .infinity)
            .padding(CicadaTheme.spacingXXL)
        case .empty:
            VStack(spacing: CicadaTheme.spacingSM) {
                Text(Copy.Graph.noCommitsTitle)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(Copy.Graph.noCommitsDetail)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity)
            .padding(CicadaTheme.spacingXXL)
        case .error:
            VStack(spacing: CicadaTheme.spacingSM) {
                Text(Copy.Graph.historyFailed)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                NeutralButton(title: Copy.Graph.retry) { Task { await loadHistoryIfNeeded() } }
                    .accessibilityLabel("Retry loading history")
            }
            .frame(maxWidth: .infinity)
            .padding(CicadaTheme.spacingXXL)
        case .entries(let rows):
            historyList(HistoryPaging.merge(rows, older: olderHistory))
        }
    }

    /// G68 — newest first. R-DG24: a neutral ring per change (hue is for data identity, P-c), the change in words,
    /// the day and who wrote it (the commit's own line only as help); then "Show in conversation" and "What changed" (G67). The
    /// two links are siblings, never one inside the other's label (the PR #20 round-2 rule that pulled
    /// `FromConversationButton` out of the expand button).
    private func historyList(_ rows: [EntityHistoryEntry]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            // Newest first, as `git log` serves it (#244; the old blame order was reversed here).
            ForEach(rows, id: \.id) { entry in
                HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                    Circle()
                        .strokeBorder(CicadaTheme.textTertiary, lineWidth: 1.5)
                        .frame(width: CicadaTheme.scaled(8), height: CicadaTheme.scaled(8))
                        .padding(.top, CicadaTheme.scaled(5))
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        // DR-54/DR-58 (final review): the commit line (`entities/<id>.md: updated (source: ep_…,
                        // trigger: sleep/…)`) is a path, an episode id and a trigger slug, so it is never on the
                        // row — the change is already in words — and stays reachable as the change line's help.
                        HStack(spacing: CicadaTheme.spacingSM) {
                            Text(HistoryWords.change(entry.changeType))
                                .font(CicadaTheme.rowFont)
                                .foregroundStyle(CicadaTheme.textPrimary)
                            Text(EntityDates.shortDay(entry.date) ?? entry.date)
                                .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                            if !entry.author.isEmpty {
                                AuthorPill(entry.author, kind: entry.authorKind, provider: entry.authorProvider)
                            }
                        }
                        .help(entry.description)
                        HStack(spacing: CicadaTheme.scaled(14)) {
                            ShowInConversationLink(sessionIds: entry.sessions,
                                                   openEpisode: ProvenanceSummary.episodeByConversation(provenanceState.value))
                            if !entry.commitHash.isEmpty { whatChangedToggle(entry) }
                        }
                        // The diff for an EXPANDED commit; `entry.diff` (includeDiff=true) wins over a fetch.
                        if isExpanded(entry) {
                            let key = diffKey(entry.commitHash)
                            if let inline = entry.diff {
                                DiffView(diff: inline)
                            } else if let fetched = commitDiffs[key] {
                                DiffView(diff: fetched)
                            } else if loadingCommits.contains(key) {
                                DiffView.loading
                            } else if diffErrors.contains(key) {
                                DiffView.error { fetchDiff(commitHash: entry.commitHash) }
                            } else {
                                DiffView.empty
                            }
                        }
                    }
                    .padding(.bottom, CicadaTheme.scaled(18))
                    Spacer(minLength: 0)
                }
            }
            olderChangesRow
        }
        .modifier(EntityTabInsets(style: style))
    }

    private var paging: HistoryPaging { historyPaging ?? HistoryPaging(truncated: entity.historyTruncated) }

    @ViewBuilder
    private var olderChangesRow: some View {
        if paging.hasMore {
            OlderChangesRow(phase: olderLoading ? .loading : (olderFailed ? .failed : .idle)) { loadOlderHistory() }
        }
    }

    private func loadOlderHistory() {
        guard !olderLoading else { return }
        var next = paging
        let id = entity.id
        olderLoading = true
        olderFailed = false
        Task {
            defer { olderLoading = false }
            do {
                let page = try await APIClient.shared.fetchEntityHistory(id: id, skip: next.nextSkip)
                guard id == entity.id else { return }
                next.received(page)
                olderHistory += page
                historyPaging = next
            } catch {
                if id == entity.id { olderFailed = true }
            }
        }
    }

    private func isExpanded(_ entry: EntityHistoryEntry) -> Bool {
        !entry.commitHash.isEmpty && expandedCommits.contains(diffKey(entry.commitHash))
    }

    private func whatChangedToggle(_ entry: EntityHistoryEntry) -> some View {
        Button { toggleCommit(entry.commitHash) } label: {
            HStack(spacing: CicadaTheme.scaled(5)) {
                DisclosureChevron(isOpen: isExpanded(entry), color: nil)
                Text(Copy.Graph.whatChanged)
            }
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(Copy.Graph.whatChangedHelp)
        .accessibilityLabel("\(Copy.Graph.whatChanged), \(entry.date)")
        .accessibilityValue(isExpanded(entry) ? "Open" : "Closed")
    }

    /// Collapse, or expand + fetch. On-demand only (the `LogoStore`/
    /// `EntitySource` precedent): a commit diff is not snapshot state, so it
    /// goes straight to `APIClient` and is cached per `DiffCacheKey` for this
    /// card.
    private func toggleCommit(_ commitHash: String) {
        let key = diffKey(commitHash)
        if expandedCommits.contains(key) {
            expandedCommits.remove(key)
            return
        }
        expandedCommits.insert(key)
        guard commitDiffs[key] == nil, !loadingCommits.contains(key) else { return }
        fetchDiff(commitHash: commitHash)
    }

    /// Fetches (or retries) one commit's diff. Captures the entity this fetch
    /// is FOR up front; if the card has since swapped to a different entity
    /// by the time the request resolves (a bare, uncancelled `Task`), the
    /// write is dropped instead of landing in the new entity's cache — on top
    /// of the `DiffCacheKey` already keeping it out of anything the new
    /// entity's rows would read.
    private func fetchDiff(commitHash: String) {
        let entityId = entity.id
        let key = diffKey(commitHash)
        diffErrors.remove(key)
        loadingCommits.insert(key)
        Task {
            do {
                let diff = try await APIClient.shared.fetchEntityCommitDiff(
                    id: entityId, commitHash: commitHash
                )
                loadingCommits.remove(key)
                guard entityId == activeEntityId else { return }
                commitDiffs[key] = diff
            } catch {
                loadingCommits.remove(key)
                guard entityId == activeEntityId else { return }
                diffErrors.insert(key)
            }
        }
    }

    // MARK: - Perspectives Tab (§3b)

    /// §3b — who believes what. R-DG22: rows, grouped under a label with its count; a disagreement between
    /// observers is one block with the divergence kind's glyph (no tinted fill, DR-7).
    private var perspectivesTab: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
            if !claimsLoaded {
                ProgressView().controlSize(.small).frame(maxWidth: .infinity, alignment: .center)
            } else if validClaims.isEmpty {
                Text(Copy.Graph.noBeliefsYet)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                ForEach(digest.divergences) { d in divergenceBlock(d) }
                ForEach(digest.groups) { group in
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                        SectionLabel(PerspectiveGroups.heading(group))
                        // Lazy: an owner-sized page holds thousands of beliefs, and a plain stack laid every row out
                        // at once (~2.7 ms a row in a debug build) before the tab could draw.
                        LazyVStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                            ForEach(group.claims) { claim in
                                BeliefRow(claim: claim) { openTimeline(for: claim) }
                            }
                        }
                        .padding(.horizontal, -CicadaTheme.scaled(10))
                    }
                }
            }
        }
        .modifier(EntityTabInsets(style: style))
    }

    private func divergenceBlock(_ d: PerspectiveGroups.Divergence) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            HStack(spacing: CicadaTheme.spacingSM) {
                KindGlyph(kind: .divergence)
                Text(Copy.Graph.observersDisagree(d.key.predicate))
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Tag(text: ClaimContext.displayName(d.key.context), dot: CicadaTheme.contextColor(d.key.context))
            }
            Text(d.line).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
        }
        .padding(CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
        .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
    }

    // MARK: - Timeline Tab (§4)

    /// R-DG23 — a belief's clock: the Timeline tab, that belief open.
    private func openTimeline(for claim: Claim) { openTimeline(for: BeliefKey(claim)) }

    private func openTimeline(for key: BeliefKey) {
        requestedKey = key
        expandedKeys.insert(key)
        selectedTab = .timeline
    }

    /// §4 — contested beliefs inline (R-DG23): a disclosure row per belief, its `BeliefTimelineView` in place.
    private var timelineTab: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if !claimsLoaded {
                ProgressView().controlSize(.small).frame(maxWidth: .infinity, alignment: .center)
            } else {
                let keys = TimelineKeys.rows(contested: digest.contested, requested: requestedKey)
                if keys.isEmpty {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        Text(Copy.Graph.noContested).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                        Text(Copy.Graph.noContestedDetail).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    }
                } else {
                    SectionLabel(TimelineKeys.heading(contested: contestedKeys.count))
                    ForEach(keys) { key in
                        TimelineKeyRow(key: key, summary: digest.summary(key),
                                       expanded: expandedKeys.contains(key)) {
                            if expandedKeys.contains(key) { expandedKeys.remove(key) } else { expandedKeys.insert(key) }
                        }
                        if expandedKeys.contains(key) {
                            BeliefTimelineView(subject: entity.id, predicate: key.predicate, context: key.context,
                                               showsHeader: false)
                                .padding(.leading, CicadaTheme.scaled(7))
                        }
                    }
                }
            }
        }
        .modifier(EntityTabInsets(style: style))
    }

    // MARK: - Claim derivations

    private var validClaims: [Claim] { digest.current }

    /// (predicate, context) keys with ≥2 claims over time (valid + superseded).
    private var contestedKeys: [BeliefKey] { digest.contested }

    /// Every caller awaits the one read in flight (the beliefs section and a tab opened together). The read is
    /// unstructured so a caller's cancellation (a tab switch removing the section) never discards it half-way; the
    /// card checks it is still on the same page before keeping the answer.
    private func loadClaimsIfNeeded() async {
        guard !claimsLoaded else { return }
        if let claimsRead { return await claimsRead.value }
        let id = entity.id
        let read = Task { @MainActor in
            // Include superseded so the timeline tab can detect contested keys.
            let fetched = try? await APIClient.shared.fetchClaims(subject: id, includeSuperseded: true)
            let loaded = fetched ?? []
            let derived = await Task.detached(priority: .userInitiated) { ClaimDigest(loaded) }.value
            // DS-3a — an answer for a page the card has left must not land under the new one.
            guard id == entity.id else { return }
            claims = loaded
            digest = derived
            claimsLoaded = true
        }
        claimsRead = read
        await read.value
        if claimsRead == read { claimsRead = nil }
    }

    private var historyState: HistoryTabState {
        HistoryTabState.resolve(embedded: entity.history, fetched: fetchedHistory, failed: historyLoadFailed)
    }

    /// One shot per card. Skipped entirely when the entity payload already
    /// carried its history — the common case once the full body has landed.
    /// A failure leaves `fetchedHistory` `nil` and sets `historyLoadFailed`
    /// instead of coercing to `[]` — coercing used to read as "no commits
    /// touch this page" AND permanently block retries (the guard below only
    /// re-fetches while `fetchedHistory == nil`). Re-selecting the History
    /// tab (or a future retry action) calls this again and clears the flag.
    private func loadHistoryIfNeeded() async {
        guard entity.history.isEmpty, fetchedHistory == nil, !historyLoading else { return }
        historyLoading = true
        historyLoadFailed = false
        do {
            fetchedHistory = try await APIClient.shared.fetchEntityHistory(id: entity.id)
        } catch {
            historyLoadFailed = true
        }
        historyLoading = false
    }

    // MARK: - Helpers

    private func buildFullMarkdown() -> String {
        // The API's verbatim file wins; the reconstruction is a fallback for
        // placeholder entities that haven't fully loaded yet.
        if !entity.rawMarkdown.isEmpty { return entity.rawMarkdown }
        return """
        ---
        type: \(entity.type.rawValue)
        status: \(entity.status.rawValue)
        confidence: \(entity.confidence)
        created: \(entity.created)
        last_referenced: \(entity.lastReferenced)
        decay_rate: \(entity.decayRate)
        decay_class: \(entity.decayClass.rawValue)
        version: \(entity.version)
        tags: [\(entity.tags.joined(separator: ", "))]
        related: [\(entity.related.joined(separator: ", "))]
        ---

        \(entity.markdownContent)
        """
    }
}

/// One Timeline row (R-DG23): a clock, the predicate, its context as a `Tag`, how many beliefs since when, a
/// disclosure chevron. 36 units, hover a fill (DR-34, DR-48).
private struct TimelineKeyRow: View {
    let key: BeliefKey
    let summary: String
    let expanded: Bool
    let toggle: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: toggle) {
            HStack(spacing: CicadaTheme.scaled(10)) {
                Image(systemName: "clock.arrow.circlepath")
                    .font(CicadaTheme.icon(.list))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
                Text(key.predicate).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                Tag(text: ClaimContext.displayName(key.context), dot: CicadaTheme.contextColor(key.context))
                Spacer(minLength: 0)
                Text(summary).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                DisclosureChevron(isOpen: expanded)
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(height: CicadaTheme.scaled(RowMetrics.oneLine))
            .rowHoverFill(hovering: hovering, selected: expanded)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .padding(.horizontal, -CicadaTheme.scaled(10))
        .onHover { hovering = $0 }
        .accessibilityValue(expanded ? "Open" : "Closed")
    }
}

// MARK: - Style (R-DG13)

/// One card, two hosts: the Graph's detail column and Clusters' card.
enum EntityCardStyle {
    /// Clusters' detail column (DS-3c, R-DL10) — the card on its block inside the column's gutter.
    case card
    /// The Graph's detail column (§5.3): no card chrome, `bgBase`, the column's leading edge (DR-11).
    case column

    /// Leading inset in units: the mock's 28 in the column, the card's 16.
    var inset: CGFloat { self == .column ? 28 : 16 }
}

private struct EntityCardChrome: ViewModifier {
    let style: EntityCardStyle

    @ViewBuilder
    func body(content: Content) -> some View {
        switch style {
        case .card: content.glassCard()
        case .column: content.background(CicadaTheme.bgBase).columnEdge()
        }
    }
}

/// The tab bodies' insets: the column's (28 leading, 20 trailing, room to scroll past the last row) or the
/// card's 16 all round.
private struct EntityTabInsets: ViewModifier {
    let style: EntityCardStyle

    @ViewBuilder
    func body(content: Content) -> some View {
        switch style {
        case .card:
            content.padding(CicadaTheme.spacingLG)
        case .column:
            content
                .padding(.leading, CicadaTheme.scaled(style.inset))
                .padding(.trailing, CicadaTheme.scaled(20))
                .padding(.top, CicadaTheme.scaled(18))
                .padding(.bottom, CicadaTheme.scaled(72))
        }
    }
}

// MARK: - Flow Layout

/// A simple wrapping horizontal layout: items flow left-to-right and wrap to
/// the next line when the available width is exhausted. Used for the entity
/// card's tag/related pills and (G67) the Contributors drill-down's entity
/// chips — shared rather than duplicated across the two views.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        FlowRows.layout(subviews, maxWidth: proposal.width ?? .infinity, spacing: spacing).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        FlowRows.place(subviews, in: bounds, spacing: spacing)
    }
}

/// The one wrapping rule behind `FlowLayout` and `ClaimFooterFlow`: items flow left to right and wrap when the width
/// is used up, and an item wider than a whole row is offered the row's width (so a `lineLimit(1)` label truncates)
/// instead of its ideal width. A flow never reports or draws wider than it was offered: the owner's page drew its
/// whole main column off the card's left edge when one flow did (a fixed-width column centres what overflows it).
enum FlowRows {
    struct Result {
        var size: CGSize
        var frames: [CGRect]
    }

    static func layout(_ subviews: Layout.Subviews, maxWidth: CGFloat, spacing: CGFloat) -> Result {
        var frames: [CGRect] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var totalWidth: CGFloat = 0

        for subview in subviews {
            var size = subview.sizeThatFits(.unspecified)
            if size.width > maxWidth {
                size = subview.sizeThatFits(ProposedViewSize(width: maxWidth, height: nil))
                size.width = min(size.width, maxWidth)
            }
            if x + size.width > maxWidth, x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            frames.append(CGRect(origin: CGPoint(x: x, y: y), size: size))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
            totalWidth = max(totalWidth, x - spacing)
        }
        return Result(size: CGSize(width: totalWidth, height: y + rowHeight), frames: frames)
    }

    static func place(_ subviews: Layout.Subviews, in bounds: CGRect, spacing: CGFloat) {
        let frames = layout(subviews, maxWidth: bounds.width, spacing: spacing).frames
        for (index, subview) in subviews.enumerated() {
            let frame = frames[index]
            subview.place(at: CGPoint(x: bounds.minX + frame.minX, y: bounds.minY + frame.minY),
                          proposal: ProposedViewSize(frame.size))
        }
    }
}

// MARK: - Wikilink Rendering
//
// The former `renderedMarkdownAttributed(_:)` lived here — a private,
// zero-call-site duplicate of `renderWikilinks` (ClaimChip.swift), superseded
// by `TranscludingMarkdownView` / `MarkdownBody`. Removed so nobody "fixes
// markdown" here and sees no effect; all entity-body rendering now flows
// through `MarkdownBody`.

/// #244 — the History tab's last row while the served page left older changes out: "Older changes" as a text button
/// (DR-40), a small spinner while it reads, and a failure in words with Retry. Never a count it does not know.
struct OlderChangesRow: View {
    enum Phase { case idle, loading, failed }

    let phase: Phase
    let action: () -> Void

    var body: some View {
        Group {
            switch phase {
            case .loading:
                ProgressView().controlSize(.small)
            case .failed:
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(Copy.Graph.olderChangesFailed)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    TextButton(title: Copy.Graph.retry, action: action)
                }
            case .idle:
                TextButton(title: Copy.Graph.olderChanges, action: action)
                    .padding(.leading, -CicadaTheme.scaled(10))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}


/// Details' Related row (owner page, 2026-10-14): the first `DetailsWords.relatedShown` names, each a link when it names
/// a page (DR-5 link), then "and K more", which opens the page's own Related section (DR-38: that section already lists
/// every one). Only the names shown are looked up: a hub's thousands of chips, each scanning the graph for its page,
/// were the lag on opening the owner's card.
struct RelatedLinksRow: View {
    let related: [String]
    let entities: [Entity]
    var onOpen: (String) -> Void
    /// Opens the page's Related section; nil when the page has none (the count is then words, not a link).
    var onMore: (() -> Void)? = nil

    var body: some View {
        let preview = DetailsWords.relatedPreview(related)
        FlowLayout(spacing: CicadaTheme.spacingMD) {
            ForEach(Array(preview.shown.enumerated()), id: \.offset) { _, rel in link(rel) }
            if preview.more > 0 { more(preview.more) }
        }
    }

    @ViewBuilder
    private func link(_ rel: String) -> some View {
        if let id = DetailsWords.relatedTarget(rel, in: entities) {
            Button { onOpen(id) } label: {
                Text(rel).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.accentText)
            }
            .buttonStyle(.cicadaPlain)
        } else {
            Text(rel).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
        }
    }

    @ViewBuilder
    private func more(_ n: Int) -> some View {
        if let onMore {
            Button(action: onMore) {
                Text(Copy.Graph.relatedMore(n)).font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.accentText)
            }
            .buttonStyle(.cicadaPlain)
            .help(Copy.Graph.relatedMoreHelp)
        } else {
            Text(Copy.Graph.relatedMore(n)).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}
