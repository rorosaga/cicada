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
    @State private var timelineKey: BeliefKey?

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
    @State private var newSourceRef = ""

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
        // Installed ONCE here, before `.sheet` below so the Belief Timeline
        // sheet's `ClaimChip`s inherit it too — see `View.wikilinkNavigation`
        // in MarkdownBody.swift. Covers the header's Summary, the rendered body,
        // transcluded embeds, and every claim chip in Perspectives/Timeline.
        .wikilinkNavigation(onSelect: navigate)
        .sheet(item: $timelineKey) { key in
            beliefTimelineSheet(key)
        }
        // A chip in the Belief Timeline sheet opens the Reader beside this
        // card; the sheet steps aside so the sentence is not under a modal
        // (the rule `ContentView` applies to the Ask sheet, R-PU20).
        .onChange(of: provenanceRouter?.revision ?? 0) { _, _ in timelineKey = nil }
        // Outermost on purpose: the Belief Timeline sheet's chips read it too.
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
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            // Rendered/Source toggle + copy
            HStack(spacing: CicadaTheme.spacingXS) {
                ViewModeButton(title: "Rendered", icon: "eye", isSelected: !showRawMarkdown) {
                    showRawMarkdown = false
                }
                ViewModeButton(title: "Source", icon: "chevron.left.forwardslash.chevron.right", isSelected: showRawMarkdown) {
                    showRawMarkdown = true
                }

                Spacer()

                Button {
                    let fullMarkdown = buildFullMarkdown()
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(fullMarkdown, forType: .string)
                } label: {
                    Image(systemName: "doc.on.doc")
                        .font(CicadaTheme.font(size: 12))
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                .buttonStyle(.cicadaPlain)
                .help("Copy markdown")
            }

            // G133: a paper leads with why it is in memory, then the dated
            // abstract — and never loads arxiv.org in a preview (R-LS19).
            if let paperDetail {
                PaperCard(detail: paperDetail)
                Divider().background(CicadaTheme.border)
            } else if entity.type == .media, let media = entity.media, media.hasURL, !media.isPaper {
                // G11: rich media preview above the body for `media`-type entities.
                MediaPreview(model: MediaPreviewModel(
                    block: media,
                    title: entity.name,
                    description: mediaDescription
                ))
                Divider().background(CicadaTheme.border)
            }

            if showRawMarkdown {
                rawMarkdownView
            } else {
                renderedMarkdownView
                if showsBeliefs, !validClaims.isEmpty {
                    WhatCicadaKnowsSection(claims: validClaims) { claim in
                        timelineKey = BeliefKey(claim)
                    }
                }
            }

            if entity.type == .location {
                Divider().background(CicadaTheme.border)
                locationSection
            }

            if !repoContexts.isEmpty {
                Divider().background(CicadaTheme.border)
                repositorySection
            }

            Divider().background(CicadaTheme.border)
            sourcesSection

            Divider().background(CicadaTheme.border)
            metadataSection

            Divider().background(CicadaTheme.border)
            WhereThisCameFromSection(entityId: entity.id, state: provenanceState)
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
            newSourceRef = ""
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
                HStack(spacing: CicadaTheme.spacingXS) {
                    Image(systemName: "folder")
                        .font(CicadaTheme.font(size: 11))
                        .foregroundStyle(CicadaTheme.entityColor(for: .location))
                    Text("Path")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Spacer()
                    Button {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(path, forType: .string)
                    } label: {
                        Image(systemName: "doc.on.doc")
                            .font(CicadaTheme.font(size: 11))
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                    .buttonStyle(.cicadaPlain)
                    .help("Copy path")
                }

                Text(path)
                    .font(CicadaTheme.monoFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .textSelection(.enabled)
                    .lineLimit(2)
                    .truncationMode(.middle)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(CicadaTheme.spacingSM)
                    .background(CicadaTheme.surfaceHover.opacity(0.5))
                    .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))

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
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Image(systemName: "chevron.left.forwardslash.chevron.right")
                    .font(CicadaTheme.font(size: 11))
                    .foregroundStyle(CicadaTheme.entityColor(for: .tool))
                Text(repoContexts.count > 1 ? "Repositories" : "Repository")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }

            ForEach(repoContexts) { repo in
                repoCard(repo)
            }
        }
    }

    private func repoCard(_ repo: RepoContext) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
                VStack(alignment: .leading, spacing: 2) {
                    if let remote = repo.remote, !remote.isEmpty {
                        Text(remote)
                            .font(CicadaTheme.font(size: 12, weight: .medium))
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    Text(repo.path)
                        .font(CicadaTheme.monoFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .textSelection(.enabled)
                }
                Spacer()
                repoStatusBadge(repo.status)
            }

            HStack(spacing: CicadaTheme.spacingXS) {
                if let branch = repo.currentBranch, !branch.isEmpty {
                    pill(branch, icon: "arrow.triangle.branch", color: CicadaTheme.accent)
                }
                if let dirty = repo.dirtyFiles, dirty > 0 {
                    pill("\(dirty) dirty", icon: "circle.fill", color: CicadaTheme.warning)
                }
                if let ahead = repo.ahead, ahead > 0 {
                    pill("↑\(ahead)", icon: nil, color: CicadaTheme.success)
                }
                if let behind = repo.behind, behind > 0 {
                    pill("↓\(behind)", icon: nil, color: CicadaTheme.danger)
                }
            }

            if let commit = repo.lastCommit, !commit.hash.isEmpty {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Text(commit.shortHash)
                        .font(CicadaTheme.monoFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Text(commit.subject)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(1)
                    Spacer()
                    Text(relativeDate(commit.dateValue))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }

            if repo.worktrees.count > 1 {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(repo.worktrees, id: \.path) { wt in
                        HStack(spacing: 4) {
                            Image(systemName: wt.isMain ? "star.fill" : "arrow.triangle.branch")
                                .font(CicadaTheme.font(size: 9))
                                .foregroundStyle(wt.isMain ? CicadaTheme.hubGold : CicadaTheme.textTertiary)
                            Text(wt.branch ?? wt.path)
                                .font(CicadaTheme.font(size: 10, design: .monospaced))
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .lineLimit(1)
                            if wt.isDirty == true {
                                Circle()
                                    .fill(CicadaTheme.warning)
                                    .frame(width: 5, height: 5)
                            }
                        }
                    }
                }
                .padding(.top, 2)
            }

            if let hint = repo.staleHint, !hint.isEmpty {
                HStack(spacing: 4) {
                    Image(systemName: "exclamationmark.triangle")
                        .font(CicadaTheme.font(size: 9))
                    Text(hint)
                        .font(CicadaTheme.font(size: 10))
                }
                .foregroundStyle(CicadaTheme.warning)
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CicadaTheme.surfaceHover.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    private func repoStatusBadge(_ status: String) -> some View {
        let (label, color): (String, Color) = {
            switch status {
            case "ok": return ("ok", CicadaTheme.success)
            case "other_device": return ("other device", CicadaTheme.textTertiary)
            case "missing": return ("missing", CicadaTheme.danger)
            case "not_a_repo": return ("not a repo", CicadaTheme.danger)
            case "git_unavailable": return ("git unavailable", CicadaTheme.warning)
            case "timeout": return ("timeout", CicadaTheme.warning)
            default: return (status, CicadaTheme.textTertiary)
            }
        }()
        return Text(label)
            .font(CicadaTheme.font(size: 10, weight: .medium))
            .foregroundStyle(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.15))
            .clipShape(Capsule())
    }

    private func pill(_ text: String, icon: String?, color: Color) -> some View {
        HStack(spacing: 3) {
            if let icon {
                Image(systemName: icon)
                    .font(CicadaTheme.font(size: 7))
            }
            Text(text)
                .font(CicadaTheme.font(size: 10, weight: .medium))
        }
        .foregroundStyle(color)
        .padding(.horizontal, 6)
        .padding(.vertical, 2)
        .background(color.opacity(0.12))
        .clipShape(Capsule())
    }

    // MARK: - Sources Section (G61)

    /// "Where to look this fact up" — a URL, a path, or a plain-English note.
    /// Distinct from `source_episodes` (where a belief came from): a source is
    /// a cheat-sheet for REFRESHING a fact.
    private var sourcesSection: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            // G118 slice 2 (§4.5) — renamed from "Sources": this is where to
            // REFRESH a fact; where a belief CAME FROM is the section below.
            Text(Copy.Provenance.lookItUpAt)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)

            ForEach(Array(sources.enumerated()), id: \.element.id) { pair in
                sourceRow(pair.element, index: pair.offset)
            }

            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "plus.circle")
                    .font(CicadaTheme.font(size: 11))
                    .foregroundStyle(CicadaTheme.textTertiary)
                TextField("Add a URL, a path, or a note…", text: $newSourceRef)
                    .textFieldStyle(.plain)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .onSubmit {
                        let ref = newSourceRef.trimmed
                        guard !ref.isEmpty else { return }
                        newSourceRef = ""
                        Task {
                            if let updated = try? await APIClient.shared.addEntitySource(
                                entityId: entity.id, ref: ref
                            ) {
                                sources = updated
                            }
                        }
                    }
            }
            .padding(CicadaTheme.spacingSM)
            .background(CicadaTheme.surface)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
        }
    }

    private func sourceRow(_ source: EntitySource, index: Int) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: source.icon)
                .font(CicadaTheme.font(size: 11))
                .foregroundStyle(CicadaTheme.textTertiary)
            VStack(alignment: .leading, spacing: 1) {
                Text(source.ref)
                    .font(CicadaTheme.font(size: 12))
                    .foregroundStyle(source.url == nil ? CicadaTheme.textSecondary : CicadaTheme.accent)
                    .lineLimit(2)
                Text([source.predicate, "added by \(source.addedBy)", source.addedAt]
                        .compactMap { $0 }.joined(separator: " · "))
                    .font(CicadaTheme.font(size: 10))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            Spacer()
            if let url = source.url {
                Button { NSWorkspace.shared.open(url) } label: {
                    Image(systemName: "arrow.up.right.square")
                        .font(CicadaTheme.font(size: 11))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .buttonStyle(.cicadaPlain)
                .help("Open")
            }
            Button {
                Task {
                    if let updated = try? await APIClient.shared.deleteEntitySource(
                        entityId: entity.id, index: index
                    ) {
                        sources = updated
                    }
                }
            } label: {
                Image(systemName: "trash")
                    .font(CicadaTheme.font(size: 11))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .buttonStyle(.cicadaPlain)
            .help("Remove source")
        }
        .padding(.vertical, 2)
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
            .background(CicadaTheme.surfaceHover.opacity(0.5))
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    private var metadataSection: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if !entity.tags.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text("Tags")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)

                    FlowLayout(spacing: 6) {
                        ForEach(entity.tags, id: \.self) { tag in
                            Text(tag)
                                .font(CicadaTheme.font(size: 11))
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .lineLimit(1)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3)
                                .background(CicadaTheme.surfaceHover)
                                .clipShape(Capsule())
                        }
                    }
                }
            }

            if !entity.related.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text("Related")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)

                    FlowLayout(spacing: 6) {
                        ForEach(entity.related, id: \.self) { rel in
                            Text(rel)
                                .font(CicadaTheme.font(size: 11))
                                .foregroundStyle(CicadaTheme.accent)
                                .lineLimit(1)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3)
                                .background(CicadaTheme.accent.opacity(0.1))
                                .clipShape(Capsule())
                        }
                    }
                }
            }

            HStack(spacing: CicadaTheme.spacingLG) {
                Label(entity.created, systemImage: "calendar")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)

                Label(entity.lastReferenced, systemImage: "clock")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)

                decayChip

                Spacer()
            }
        }
    }

    // MARK: - Decay chip (G66 §1.7)
    //
    // The raw `decay_rate` number was never meaningful to a reader ("0.05" says
    // nothing); the class does. Tapping the chip opens a picker that PUTs the
    // override — the user's authority over how fast the agent forgets.

    private var shownDecayClass: DecayClass { pendingDecayClass ?? entity.decayClass }

    private var decayChip: some View {
        Menu {
            ForEach(DecayClass.allCases) { option in
                Button {
                    setDecay(option)
                } label: {
                    Label(
                        "\(option.label) — \(option.blurb)",
                        systemImage: option == shownDecayClass ? "checkmark" : option.icon
                    )
                }
            }
        } label: {
            HStack(spacing: 4) {
                Image(systemName: shownDecayClass.icon)
                    .font(CicadaTheme.font(size: 9))
                Text(shownDecayClass.chipText)
                    .font(CicadaTheme.captionFont)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(decayChipTint.opacity(0.15))
            .foregroundStyle(decayChipTint)
            .clipShape(Capsule())
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .help("How fast this entity fades when it stops being mentioned")
        .accessibilityLabel("Decay class: \(shownDecayClass.label)")
    }

    private var decayChipTint: Color {
        switch shownDecayClass {
        case .evergreen: CicadaTheme.diffAdded
        case .durable: CicadaTheme.decayDurable
        case .active: CicadaTheme.textSecondary
        case .volatile: CicadaTheme.decayVolatile
        }
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

    // G68 §2.10 — three branches, resolved by `HistoryTabState`: a spinner
    // while the fetch is in flight, an empty state once it's confirmed there
    // is nothing, and (the common case) the existing G67 diff-expansion list.
    @ViewBuilder
    private var historyTab: some View {
        switch historyState {
        case .loading:
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text("Reading git history…")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .frame(maxWidth: .infinity)
            .padding(CicadaTheme.spacingXXL)

        case .empty:
            VStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "clock.arrow.circlepath")
                    .font(CicadaTheme.font(size: 26))
                    .foregroundStyle(CicadaTheme.textTertiary)
                Text("No commits touch this page yet")
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("It appears here once a Sleep cycle writes to it.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity)
            .padding(CicadaTheme.spacingXXL)

        case .error:
            VStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "exclamationmark.triangle")
                    .font(CicadaTheme.font(size: 26))
                    .foregroundStyle(CicadaTheme.danger)
                Text("Couldn't load history")
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Button("Retry") { Task { await loadHistoryIfNeeded() } }
                    .buttonStyle(.bordered)
                    .accessibilityLabel("Retry loading history")
            }
            .frame(maxWidth: .infinity)
            .padding(CicadaTheme.spacingXXL)

        case .entries(let rows):
            historyList(rows)
        }
    }

    private func historyList(_ rows: [EntityHistoryEntry]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(rows.reversed().enumerated()), id: \.element.id) { index, entry in
                HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                    // Timeline
                    VStack(spacing: 0) {
                        Circle()
                            .fill(index == 0
                                  ? CicadaTheme.success
                                  : CicadaTheme.historyColor(for: entry.changeType))
                            .frame(width: 10, height: 10)

                        if index < rows.count - 1 {
                            Rectangle()
                                .fill(CicadaTheme.border)
                                .frame(width: 1)
                                .frame(maxHeight: .infinity)
                        }
                    }
                    .frame(width: 10)

                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        historyRowButton(entry)

                        // The diff for an EXPANDED commit. `entry.diff` (present
                        // only when history was fetched with includeDiff=true)
                        // wins so we never re-fetch what we already hold.
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
                    .padding(.bottom, CicadaTheme.spacingLG)

                    Spacer()
                }
            }
        }
        .modifier(EntityTabInsets(style: style))
    }

    private func isExpanded(_ entry: EntityHistoryEntry) -> Bool {
        !entry.commitHash.isEmpty && expandedCommits.contains(diffKey(entry.commitHash))
    }

    /// The tappable summary line, plus the "from conversation" affordance as
    /// its own SIBLING control (PR #20 round-2 review fix). `FromConversationButton`
    /// used to be nested inside `historyRowLabel`, which is itself the LABEL
    /// of the row-expansion `Button` below — a `Button` inside a `Button`'s
    /// label, which makes AppKit/SwiftUI's tap targeting ambiguous (a tap
    /// meant for the popover could instead toggle diff expansion). Pulling it
    /// out to a trailing sibling in this `HStack` gives each control its own
    /// hit region with no ambiguity, while keeping both reachable via the
    /// same row. A row with no `commitHash` (an older backend that didn't
    /// surface one) renders its summary as plain, un-tappable text rather
    /// than a button that could never do anything — the conversation
    /// affordance still renders independently of that.
    @ViewBuilder
    private func historyRowButton(_ entry: EntityHistoryEntry) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingXS) {
            if entry.commitHash.isEmpty {
                historyRowLabel(entry, expandable: false)
            } else {
                Button {
                    toggleCommit(entry.commitHash)
                } label: {
                    historyRowLabel(entry, expandable: true)
                }
                .buttonStyle(.cicadaPlain)
                .help("Show what changed in this commit")
                .accessibilityLabel("Commit \(entry.date) by \(entry.author)")
            }

            FromConversationButton(sessionIds: entry.sessions,
                                   openEpisode: ProvenanceSummary.episodeByConversation(provenanceState.value))
        }
    }

    private func historyRowLabel(_ entry: EntityHistoryEntry, expandable: Bool) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingXS) {
                if expandable {
                    Image(systemName: isExpanded(entry) ? "chevron.down" : "chevron.right")
                        .font(CicadaTheme.font(size: 9, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                Text(entry.date)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                // M3 (backlog A2): who authored this commit — with the same
                // face and name the claim footer and the contributors strip
                // give them (G118 slice 2, §4.6).
                if !entry.author.isEmpty {
                    AuthorPill(entry.author, kind: entry.authorKind, provider: entry.authorProvider)
                }
            }

            Text(entry.description)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
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
    //
    // The subject's claims grouped by observer, each group a labeled section
    // (Observer.label + sfSymbol badge) of claim chips. Where two observers
    // disagree on the same (predicate, context), a divergence callout names the
    // "who believes what" contradiction-across-observers.

    private var perspectivesTab: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            if !claimsLoaded {
                ProgressView().controlSize(.small)
                    .frame(maxWidth: .infinity, alignment: .center)
            } else if validClaims.isEmpty {
                claimsEmptyState
            } else {
                ForEach(divergences, id: \.self) { d in
                    divergenceCallout(d)
                }
                ForEach(observerGroups, id: \.0.id) { observer, group in
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        HStack(spacing: CicadaTheme.spacingXS) {
                            ObserverBadge(observer)
                            Text("\(group.count)")
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                        ForEach(group) { claim in
                            ClaimChip(claim: claim, onOpenTimeline: {
                                timelineKey = BeliefKey(claim)
                            })
                        }
                    }
                }
            }
        }
        .modifier(EntityTabInsets(style: style))
    }

    // MARK: - Timeline Tab (§4)
    //
    // Lists the subject's CONTESTED keys — any (predicate, context) with ≥2
    // claims over time — and drills into BeliefTimelineView on tap.

    private var timelineTab: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if !claimsLoaded {
                ProgressView().controlSize(.small)
                    .frame(maxWidth: .infinity, alignment: .center)
            } else if contestedKeys.isEmpty {
                VStack(spacing: CicadaTheme.spacingSM) {
                    Image(systemName: "clock.badge.questionmark")
                        .font(CicadaTheme.font(size: 24))
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Text("No contested beliefs yet.")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    Text("A belief becomes contested when a (predicate, context) has changed over time.")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, CicadaTheme.spacingXL)
            } else {
                Text("Contested beliefs")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                ForEach(contestedKeys, id: \.id) { key in
                    Button {
                        timelineKey = key
                    } label: {
                        HStack(spacing: CicadaTheme.spacingSM) {
                            Image(systemName: "clock.arrow.circlepath")
                                .font(CicadaTheme.font(size: 12))
                                .foregroundStyle(CicadaTheme.accent)
                            Text(key.predicate)
                                .font(CicadaTheme.bodyFont)
                                .foregroundStyle(CicadaTheme.textPrimary)
                            ContextPill(key.context)
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(CicadaTheme.font(size: 10))
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                        .padding(CicadaTheme.spacingMD)
                        .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    }
                    .buttonStyle(.cicadaPlain)
                }
            }
        }
        .modifier(EntityTabInsets(style: style))
    }

    private func beliefTimelineSheet(_ key: BeliefKey) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Spacer()
                Button { timelineKey = nil } label: {
                    Image(systemName: "xmark")
                        .font(CicadaTheme.font(size: 12, weight: .medium))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .frame(width: 28, height: 28)
                        .background(CicadaTheme.surfaceHover)
                        .clipShape(Circle())
                }
                .buttonStyle(.cicadaPlain)
                .padding(CicadaTheme.spacingMD)
            }
            ScrollView {
                BeliefTimelineView(subject: entity.id, predicate: key.predicate, context: key.context)
            }
        }
        .frame(minWidth: 460, minHeight: 420)
        .background(CicadaTheme.background)
    }

    private var claimsEmptyState: some View {
        VStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: "person.2.slash")
                .font(CicadaTheme.font(size: 24))
                .foregroundStyle(CicadaTheme.textTertiary)
            Text("No claims for this subject yet.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CicadaTheme.spacingXL)
    }

    private func divergenceCallout(_ d: Divergence) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.bubble.fill")
                    .font(CicadaTheme.font(size: 11))
                    .foregroundStyle(CicadaTheme.warning)
                Text("Observers disagree on \(d.predicate)")
                    .font(CicadaTheme.font(size: 12, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                ContextPill(d.context)
            }
            ForEach(Array(d.byObserver.enumerated()), id: \.offset) { _, pair in
                HStack(spacing: 4) {
                    ObserverBadge(pair.0)
                    Text("asserts")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Text(pair.1)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
            }
        }
        .padding(CicadaTheme.spacingMD)
        .background(CicadaTheme.warning.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
        .overlay(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .stroke(CicadaTheme.warning.opacity(0.3), lineWidth: 1)
        )
    }

    // MARK: - Claim derivations

    private var validClaims: [Claim] { claims.filter { $0.isValid } }

    /// Valid claims grouped by observer, observer order stable (agent, rodrigo,
    /// then externals).
    private var observerGroups: [(Observer, [Claim])] {
        let grouped = Dictionary(grouping: validClaims, by: { $0.observer })
        return grouped.sorted { observerRank($0.key) < observerRank($1.key) }
            .map { ($0.key, $0.value) }
    }

    private func observerRank(_ o: Observer) -> Int {
        switch o {
        case .agent: return 0
        case .rodrigo: return 1
        case .external: return 2
        }
    }

    struct Divergence: Hashable {
        let predicate: String
        let context: String
        let byObserver: [(Observer, String)]
        static func == (l: Divergence, r: Divergence) -> Bool {
            l.predicate == r.predicate && l.context == r.context
        }
        func hash(into h: inout Hasher) { h.combine(predicate); h.combine(context) }
    }

    /// (predicate, context) keys where ≥2 distinct observers assert different
    /// objects among the currently-valid claims.
    private var divergences: [Divergence] {
        let byKey = Dictionary(grouping: validClaims, by: { "\($0.predicate)|\($0.context)" })
        var out: [Divergence] = []
        for (_, group) in byKey {
            let distinctObservers = Set(group.map { $0.observer })
            let distinctObjects = Set(group.map { $0.object })
            if distinctObservers.count >= 2 && distinctObjects.count >= 2, let first = group.first {
                let pairs = group.map { ($0.observer, $0.object) }
                out.append(Divergence(predicate: first.predicate, context: first.context, byObserver: pairs))
            }
        }
        return out
    }

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

// MARK: - View Mode Button (Rendered / Source)

private struct ViewModeButton: View {
    let title: String
    let icon: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .font(CicadaTheme.font(size: 10, weight: .medium))
                Text(title)
                    .font(CicadaTheme.font(size: 11, weight: .medium))
            }
            .foregroundStyle(isSelected ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(isSelected ? CicadaTheme.surfaceHover : .clear)
            .clipShape(RoundedRectangle(cornerRadius: 4))
        }
        .buttonStyle(.cicadaPlain)
        .help("\(title) view")
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
