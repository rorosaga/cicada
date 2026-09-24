import SwiftUI

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
    /// R-DG23 — the Timeline tab's open rows, and the one a belief's clock asked for.
    @State private var expandedKeys: Set<BeliefKey> = []
    @State private var requestedKey: BeliefKey?

    // Location listing (issue #7). Loaded lazily on appear for `.location`
    // entities; nil while loading or when no path/endpoint is available.
    @State private var locationListing: LocationListing?

    // Repository context (G9 companion). Loaded lazily on appear for
    // `.project`/`.directory` entities; empty while loading, on 404, or when
    // the entity carries no `repos:` key — the section renders nothing in
    // all three cases (see `fetchEntityRepos`).
    @State private var repoContexts: [RepoContext] = []

    // Fact sources (G61) — "where to look this fact up" refresh references.
    // Loaded on every entity (unlike repos/location, not gated by entity type).
    @State private var sources: [EntitySource] = []
    /// G133 — a paper page's two tiers, fetched once per open.
    @State private var paperDetail: PaperDetail?
    /// R-DG21 / DR-39 — the Details disclosure, collapsed until this viewer opens it, then remembered.
    @AppStorage(DetailsWords.openKey) private var detailsOpen = false

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
    /// R-DG13 — `.column` on the Graph, `.card` in Clusters (its page frame is DS-3b's).
    let style: EntityCardStyle
    /// The column's × — the page closes the column and its Reader together (R-DG7). Nil: `clearSelection()`.
    let onClose: (() -> Void)?
    /// DR-28 — the page decides what Esc closes (the Reader first). Clusters passes none, so Esc there no longer
    /// clears the Graph's selection behind it.
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

    private var isStub: Bool { entity.rawMarkdown.isEmpty }

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
                tabs: EntityTabs.tabs(claims: claimsLoaded ? claims : nil,
                                      historyCount: EntityTabs.historyCount(embedded: entity.history, fetched: fetchedHistory)),
                selection: $selectedTab,
                inset: style.inset)
            ScrollView {
                switch selectedTab {
                case .content: contentTab
                case .perspectives: perspectivesTab
                case .history: historyTab
                case .timeline: timelineTab
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
            case .history: Task { await loadHistoryIfNeeded() }
            case .perspectives, .timeline: Task { await loadClaimsIfNeeded() }
            case .content: break
            }
        }
        // Installed ONCE here — see `View.wikilinkNavigation` in MarkdownBody.swift. Covers the header's Summary,
        // the rendered body, transcluded embeds, and every claim chip in Perspectives and the inline Timeline.
        // The Belief Timeline sheet (and its step-aside for the Reader) retired with R-DG23.
        .wikilinkNavigation(onSelect: navigate)
        // Outermost on purpose: every evidence chip in the tabs reads it.
        .environment(\.evidenceDocIndex, EvidenceDocIndex.from(provenanceState.value))
        .task(id: entity.id) { await loadProvenance() }
        // R-DG16 — the tab counts need the claims when the column opens, not when a tab is tapped. At the
        // card's level: a tab switch removes `contentTab` and would cancel a task hung there.
        .task(id: entity.id) { await loadClaimsIfNeeded() }
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

    private var contentTab: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingCard) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                HStack(spacing: 0) {
                    TextTabs(tabs: EntityBodyView.tabs, selection: Binding(
                        get: { showRawMarkdown ? .source : .rendered },
                        set: { if let view = $0 { showRawMarkdown = view == .source } }))
                        .padding(.leading, -CicadaTheme.scaled(TextTabs<EntityBodyView>.horizontalPadding))
                    Spacer(minLength: 0)
                    IconButton(systemName: "doc.on.doc", help: Copy.Graph.copyMarkdown) {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(buildFullMarkdown(), forType: .string)
                    }
                }
                // G133: a paper leads with why it is in memory, then the dated abstract — and never loads
                // arxiv.org in a preview (R-LS19).
                if let paperDetail {
                    PaperCard(detail: paperDetail)
                } else if entity.type == .media, let media = entity.media, media.hasURL, !media.isPaper {
                    // G11: rich media preview above the body for `media`-type entities.
                    MediaPreview(model: MediaPreviewModel(block: media, title: entity.name, description: mediaDescription))
                }
                if showRawMarkdown { rawMarkdownView } else { renderedMarkdownView }
            }
            if entity.type == .location { locationSection }
            if !repoContexts.isEmpty { repositorySection }
            if !showRawMarkdown, showsBeliefs, !validClaims.isEmpty {
                WhatCicadaKnowsSection(claims: validClaims) { claim in openTimeline(for: claim) }
            }
            WhereThisCameFromSection(entityId: entity.id, state: provenanceState)
            // `.id` — the add field's draft belongs to one page, as the card's own field was reset per id.
            LookItUpSection(entityId: entity.id, sources: $sources).id(entity.id)
            detailsSection
        }
        .modifier(EntityTabInsets(style: style))
        .task(id: entity.id) {
            // G124 R11 — a card open is a read. Fire-and-forget on its own
            // Task so a slow ledger never delays the sources fetch below.
            Task { await APIClient.shared.recordEntityRead(id: entity.id) }
            // Reset before (re)fetching so swapping between entities can't show
            // a previous entity's location/repo/sources data. `.task(id:)`
            // already guarantees this runs once per id, so no extra "loaded"
            // guard is needed.
            locationListing = nil
            repoContexts = []
            sources = []
            paperDetail = nil
            pendingDecayClass = nil
            activeEntityId = entity.id
            expandedCommits = []
            commitDiffs = [:]
            loadingCommits = []
            diffErrors = []
            sources = (try? await APIClient.shared.fetchEntitySources(entityId: entity.id)) ?? []
            // Gated on what the graph-node STUB already knows (task 7 review
            // r1): the card opens on a stub whose `media` is nil, and the
            // full-entity swap below keeps the same `.task(id:)`, so a check
            // on `media?.isPaper` alone never fired on a first open. The
            // endpoint 404s for a non-paper, which `try?` reads as nil.
            if Self.wantsPaperDetail(type: entity.type, media: entity.media) {
                paperDetail = try? await APIClient.shared.fetchPaperDetail(id: entity.id)
            }
            // §5.7 — the card opened on the graph-node stub, whose
            // `markdownContent` is the server's short `summary` (already
            // rendered above, so there is never an empty card). Upgrade it to
            // the full entity through the Store's memoised cache; the swap
            // lands via `graphVM.selectedEntity`/`entities`, which is what
            // feeds this view its `entity`.
            await graphVM.loadFullEntity(id: entity.id)
            // Only location entities have a directory listing to fetch.
            if entity.type == .location {
                locationListing = try? await APIClient.shared.fetchLocationListing(id: entity.id)
            }
            // Only project/directory entities carry a `repos:` frontmatter key.
            if entity.type == .project || entity.type == .directory {
                repoContexts = (try? await APIClient.shared.fetchEntityRepos(entityId: entity.id)) ?? []
            }
        }
    }

    // MARK: - Location Section (issue #7)
    //
    // For `.location` entities, shows the declared directory path (monospace,
    // copyable) and a bounded listing of its immediate children. Degrades
    // quietly: no path / inaccessible / endpoint absent → renders nothing.

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
                locationNote("Directory not found.", icon: "questionmark.folder")
            } else if !listing.accessible {
                locationNote("Permission denied — can't list this directory.",
                             icon: "lock")
            } else if listing.entries.isEmpty {
                locationNote("Empty directory.", icon: "tray")
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
                                .font(CicadaTheme.font(size: 12))
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
                        Text("…listing truncated")
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
    // key, shows the live local-checkout state per declared repo — remote,
    // branch, dirty/ahead/behind counts, last commit, worktrees, and any
    // `stale_hint`. Gated entirely by `!repoContexts.isEmpty` in `contentTab`,
    // so this only ever renders once data has actually arrived — no empty
    // section, no loading skeleton. NOT INTEGRATION-TESTED against a live
    // backend (built in parallel by another agent).

    private var repositorySection: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(repoContexts.count > 1 ? Copy.Graph.repositories : Copy.Graph.repository)
            ForEach(repoContexts) { repoBlock($0) }
        }
    }

    /// G9 — live git context, resolved on demand and never cached. R-DG21: words and neutral tags, one block on
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
        }
        .padding(CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
        .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
    }

    private func copyPath(_ p: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(p, forType: .string)
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

    /// The entity body with the sections that already render in their own
    /// dedicated chrome (`## Summary` → the header, R-DG15; `## Description` → media
    /// hero/website card) removed, so the rendered markdown view below doesn't
    /// show them a second time. The claims fence goes first (R-FX8).
    private var bodyForRendering: String {
        // R-DG15 — a stub's markdown IS the preview the header already shows.
        guard !isStub else { return "" }
        let prose = EntityProse.stripClaimsFence(entity.markdownContent)
        return EntityProse.stripSection(named: "## Description",
                                        from: EntityProse.stripSection(named: "## Summary", from: prose))
    }

    /// R-FX11 — media pages have their own card (a paper's lists its why).
    private var showsBeliefs: Bool {
        entity.type != .media
            && EntityProse.showsBeliefs(markdown: entity.markdownContent, isStub: entity.rawMarkdown.isEmpty)
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

            // Inline transclusion (§1): tokenize the body into text/embed segments
            // and render `![[…]]` embeds as nested collapsible cards. Falls back to
            // plain wikilink rendering for bodies with no embeds. Summary /
            // Description are stripped here — they already render in their own
            // chrome (the header, R-DG15 / media hero) and would otherwise double.
            TranscludingMarkdownView(body: bodyForRendering)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var rawMarkdownView: some View {
        // Prefer the verbatim file from the API (transparency: this is the
        // exact markdown on disk, frontmatter included). The reconstruction
        // below only covers placeholder entities that haven't fully loaded.
        let source = entity.rawMarkdown.isEmpty ? buildFullMarkdown() : entity.rawMarkdown

        return Text(source)
            .font(CicadaTheme.monoFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(CicadaTheme.spacingMD)
            .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
            .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
    }

    /// R-DG21 / DR-39 — secondary detail starts collapsed; each viewer's choice is remembered.
    private var detailsSection: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Button { detailsOpen.toggle() } label: {
                HStack(spacing: CicadaTheme.scaled(6)) {
                    Image(systemName: detailsOpen ? "chevron.down" : "chevron.right")
                        .font(CicadaTheme.font(size: 10, weight: .semibold))
                        .accessibilityHidden(true)
                    Text(Copy.Graph.details).foregroundStyle(CicadaTheme.textSecondary)
                    if !detailsOpen {
                        Text(Copy.Graph.detailsSummary).foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
                .font(CicadaTheme.metaMediumFont)
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityValue(detailsOpen ? "Open" : "Closed")
            if detailsOpen {
                Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: CicadaTheme.spacingMD,
                     verticalSpacing: CicadaTheme.scaled(10)) {
                    if !entity.tags.isEmpty {
                        GridRow {
                            detailLabel(Copy.Graph.tags)
                            FlowLayout(spacing: 6) { ForEach(entity.tags, id: \.self) { Tag(text: $0) } }
                        }
                    }
                    if !entity.related.isEmpty {
                        GridRow {
                            detailLabel(Copy.Graph.related)
                            FlowLayout(spacing: CicadaTheme.spacingMD) {
                                ForEach(entity.related, id: \.self) { rel in relatedLink(rel) }
                            }
                        }
                    }
                    GridRow {
                        detailLabel(Copy.Graph.firstNoted)
                        detailValue(EntityDates.day(entity.created) ?? "—")
                    }
                    GridRow {
                        detailLabel(Copy.Graph.lastMentioned)
                        detailValue(DetailsWords.lastMentioned(entity.lastReferenced, now: .now))
                    }
                    GridRow {
                        detailLabel(Copy.Graph.fades)
                        fadesMenu
                    }
                }
            }
        }
    }

    private func detailLabel(_ text: String) -> some View {
        Text(text).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            .frame(width: CicadaTheme.scaled(112), alignment: .leading)
    }

    private func detailValue(_ text: String) -> some View {
        Text(text).font(CicadaTheme.font(size: 13)).foregroundStyle(CicadaTheme.textSecondary)
    }

    /// A related name opens its page when one matches (DR-5 link); otherwise it is plain text.
    @ViewBuilder
    private func relatedLink(_ rel: String) -> some View {
        if let id = DetailsWords.relatedTarget(rel, in: graphVM.entities) {
            Button { navigate(to: id) } label: {
                Text(rel).font(CicadaTheme.font(size: 13, weight: .medium)).foregroundStyle(CicadaTheme.accentText)
            }
            .buttonStyle(.cicadaPlain)
        } else {
            detailValue(rel)
        }
    }

    // MARK: - Fades (G66 §1.7)
    //
    // The raw `decay_rate` number was never meaningful to a reader; the class is. The menu PUTs the override —
    // the person's authority over how fast the agent forgets.

    private var shownDecayClass: DecayClass { pendingDecayClass ?? entity.decayClass }

    private var fadesMenu: some View {
        Menu {
            ForEach(DecayClass.allCases) { option in
                Button { setDecay(option) } label: {
                    Label("\(DetailsWords.fades(option)) — \(option.blurb)",
                          systemImage: option == shownDecayClass ? "checkmark" : option.icon)
                }
            }
        } label: {
            HStack(spacing: CicadaTheme.scaled(6)) {
                Text(DetailsWords.fades(shownDecayClass))
                Image(systemName: "chevron.down").font(CicadaTheme.font(size: 9, weight: .semibold))
            }
            .font(CicadaTheme.font(size: 13))
            .foregroundStyle(CicadaTheme.textSecondary)
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .help(Copy.Graph.fadesHelp)
        .accessibilityLabel("\(Copy.Graph.fades): \(DetailsWords.fades(shownDecayClass))")
    }

    private func setDecay(_ option: DecayClass) {
        guard option != entity.decayClass else { return }
        pendingDecayClass = option  // optimistic: the chip flips immediately
        Task {
            do {
                _ = try await APIClient.shared.setDecayClass(entityId: entity.id, option)
                await graphVM.reloadEntity(id: entity.id)
            } catch {
                // Leave the server's value in place rather than lying about it.
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
            historyList(rows)
        }
    }

    /// G68 — newest first. R-DG24: a neutral ring per change (hue is for data identity, P-c), the change in words,
    /// the day and who wrote it (the commit's own line only as help); then "Show in conversation" and "What changed" (G67). The
    /// two links are siblings, never one inside the other's label (the PR #20 round-2 rule that pulled
    /// `FromConversationButton` out of the expand button).
    private func historyList(_ rows: [EntityHistoryEntry]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(rows.reversed(), id: \.id) { entry in
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
        }
        .modifier(EntityTabInsets(style: style))
    }

    private func isExpanded(_ entry: EntityHistoryEntry) -> Bool {
        !entry.commitHash.isEmpty && expandedCommits.contains(diffKey(entry.commitHash))
    }

    private func whatChangedToggle(_ entry: EntityHistoryEntry) -> some View {
        Button { toggleCommit(entry.commitHash) } label: {
            HStack(spacing: CicadaTheme.scaled(5)) {
                Image(systemName: isExpanded(entry) ? "chevron.down" : "chevron.right")
                    .font(CicadaTheme.font(size: 9, weight: .semibold))
                    .accessibilityHidden(true)
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
                    .font(CicadaTheme.font(size: 13))
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                ForEach(PerspectiveGroups.divergences(claims)) { d in divergenceBlock(d) }
                ForEach(PerspectiveGroups.of(claims)) { group in
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                        SectionLabel(PerspectiveGroups.heading(group))
                        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
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
    private func openTimeline(for claim: Claim) {
        let key = BeliefKey(claim)
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
                let keys = TimelineKeys.rows(claims: claims, requested: requestedKey)
                if keys.isEmpty {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        Text(Copy.Graph.noContested).font(CicadaTheme.font(size: 13)).foregroundStyle(CicadaTheme.textSecondary)
                        Text(Copy.Graph.noContestedDetail).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    }
                } else {
                    SectionLabel(TimelineKeys.heading(contested: contestedKeys.count))
                    ForEach(keys) { key in
                        TimelineKeyRow(key: key, summary: TimelineKeys.summary(key, claims: claims),
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

    private var validClaims: [Claim] { claims.filter { $0.isValid } }

    /// (predicate, context) keys with ≥2 claims over time (valid + superseded).
    private var contestedKeys: [BeliefKey] { EntityTabs.contested(claims) }

    private func loadClaimsIfNeeded() async {
        guard !claimsLoaded else { return }
        // Include superseded so the timeline tab can detect contested keys.
        let fetched = try? await APIClient.shared.fetchClaims(subject: entity.id, includeSuperseded: true)
        // DS-3a — a load cancelled by a swap or a close must not read as "no beliefs" (R-DG16's counts).
        guard !Task.isCancelled else { return }
        claims = fetched ?? []
        claimsLoaded = true
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
                Image(systemName: expanded ? "chevron.down" : "chevron.right")
                    .font(CicadaTheme.font(size: 10, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(height: CicadaTheme.scaled(RowMetrics.oneLine))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(expanded ? CicadaTheme.bgSelected : (hovering ? CicadaTheme.bgHover : Color.clear)))
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
    /// Clusters' detail page — the card on its block, until DS-3b restyles that page.
    case card
    /// The Graph's detail column (§5.3): no card chrome, `bgBase`, the column's leading edge (DR-11).
    case column

    /// Leading inset in units: the mock's 28 in the column, the card's 16.
    var inset: CGFloat { self == .column ? 28 : 16 }
}

/// R-DG21 — Rendered · Source as text tabs.
enum EntityBodyView: Hashable {
    case rendered, source

    static let tabs: [TextTab<EntityBodyView>] = [
        TextTab(id: .rendered, label: Copy.Graph.rendered),
        TextTab(id: .source, label: Copy.Graph.source),
    ]
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
        let result = layout(subviews: subviews, in: proposal.width ?? .infinity)
        return result.size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let positions = layout(subviews: subviews, in: bounds.width)
        for (index, subview) in subviews.enumerated() {
            let pt = positions.points[index]
            subview.place(at: CGPoint(x: bounds.minX + pt.x, y: bounds.minY + pt.y), proposal: .unspecified)
        }
    }

    private func layout(subviews: Subviews, in maxWidth: CGFloat) -> (size: CGSize, points: [CGPoint]) {
        var points: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var totalWidth: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth, x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            points.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
            totalWidth = max(totalWidth, x - spacing)
        }
        return (CGSize(width: totalWidth, height: y + rowHeight), points)
    }
}

// MARK: - Wikilink Rendering
//
// The former `renderedMarkdownAttributed(_:)` lived here — a private,
// zero-call-site duplicate of `renderWikilinks` (ClaimChip.swift), superseded
// by `TranscludingMarkdownView` / `MarkdownBody`. Removed so nobody "fixes
// markdown" here and sees no effect; all entity-body rendering now flows
// through `MarkdownBody`.
