import SwiftUI

/// A harness's conversations (G124 §2): title, age, the pages each wrote, Resume when the backend says `resumable`.
/// Fetched on demand through `/conversations/recent?harness=` (R5) — no Store domain, like the contributor commit
/// drill-down. Resume goes through the existing endpoint: transcripts are never read (G48 — `isfile()` only).
///
/// Sources v4 (owner 2026-10-19: the always-open "Filter by title" field "fits super awkwardly with the stuff at the
/// top") — find lives in the list's own header, behind its magnifier and ⌘F (DR-46: in-page find opens on ask), not
/// under the source's header. It is kept rather than dropped: the list holds the newest 200 conversations, and find is
/// the one way to reach an older one by title (`searchBeyondCap`) and where the palette's conversation hand-off lands.
struct HarnessConversationsView: View {
    let source: SourceOverview
    var onSelectEntity: ((String) -> Void)?
    /// source-page-v3 — on a source page the page's one search drives this list (`external`), the list draws no head
    /// or scroll of its own, shows at most `cap` conversations and then "All N" (`onAll`, DR-81).
    var external: String? = nil
    var cap: Int? = nil
    var onAll: (() -> Void)? = nil

    init(source: SourceOverview, onSelectEntity: ((String) -> Void)? = nil, query: String? = nil, cap: Int? = nil,
         onAll: (() -> Void)? = nil) {
        self.source = source
        self.onSelectEntity = onSelectEntity
        self.external = query
        self.cap = cap
        self.onAll = onAll
    }

    @State private var viewModel = ConversationsViewModel()
    @State private var loadedOnce = false
    @State private var ownQuery = ""
    @State private var findOpen = false
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router

    private var query: String { external ?? ownQuery }

    /// R-SU20/R-SU22 — the loaded page filtered in place (newest first, never
    /// re-ranked), then any older matches the capped page could not hold.
    private var visible: [ConversationSummary] {
        ConversationSearch.merge(local: ConversationFilter.apply(viewModel.conversations, query: query),
                                 server: viewModel.beyondCap(for: query))
    }

    var body: some View {
        if external != nil { embedded } else { standalone }
    }

    /// source-page-v3 — the rows alone, under the page's search.
    private var embedded: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if let err = viewModel.errorMessage {
                Text(err).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                NeutralButton(title: "Retry", size: .compact, help: "Retry loading conversations") {
                    Task { await load() }
                }
            } else if !viewModel.hasLoaded {
                ListSkeleton(message: "Loading conversations…", rows: 3)
            } else if visible.isEmpty {
                Text(query.isEmpty ? "No conversations from this source yet." : Copy.SourcePage.noMatch(query))
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                if !query.isEmpty { SearchAllMemoryRow(query: query) }
            } else {
                let rows = cap.map { Array(visible.prefix($0)) } ?? visible
                LazyVStack(spacing: CicadaTheme.spacingSM) {
                    ForEach(rows) { conversation in
                        ConversationRow(
                            conversation: conversation,
                            onResume: { Task { await act(await viewModel.resume(conversation.id)) } },
                            onCopy: { Task { await act(await viewModel.copyCommand(for: conversation.id)) } },
                            onSelectEntity: onSelectEntity,
                            inSourceList: true
                        )
                    }
                }
                if let cap, visible.count > cap, let onAll {
                    TextButton(title: Copy.SourcePage.all(visible.count), help: Copy.SourcePage.allHelp, action: onAll)
                }
            }
        }
        .task {
            guard !loadedOnce else { return }
            loadedOnce = true
            await load()
        }
        .task(id: "\(viewModel.conversations.count)|\(query)") {
            try? await Task.sleep(for: SearchTiming.serverDebounce)
            guard !Task.isCancelled else { return }
            await viewModel.searchBeyondCap(query: query, harness: source.harness,
                                            origin: source.harness == nil ? source.origins.first : nil)
        }
    }

    private var standalone: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                SectionLabel(Copy.conversationsTitle)
                Spacer(minLength: CicadaTheme.spacingSM)
                PageFindButton(isOpen: $findOpen)
            }
            .frame(minHeight: CicadaTheme.scaled(28))
            if findOpen {
                PageFindRow(text: $ownQuery, isOpen: $findOpen, prompt: Copy.conversationsFind)
            }
            if let err = viewModel.errorMessage {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    Text(err).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                    // DR-40 — one of the four buttons, never the native bordered one.
                    NeutralButton(title: "Retry", size: .compact, help: "Retry loading conversations") {
                        Task { await load() }
                    }
                    .accessibilityLabel("Retry loading conversations")
                }
            } else if !viewModel.hasLoaded {
                // DR-43 — the first read is the list pages' own state: words over a still skeleton, no spinner.
                ListSkeleton(message: "Loading conversations…", rows: 3)
                    .padding(.leading, -CicadaTheme.scaled(10))
            } else if visible.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    Text(query.isEmpty ? "No conversations from this source yet." : "No titles match “\(query)”.")
                        .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                    if !query.isEmpty { SearchAllMemoryRow(query: query) }
                }
            } else {
                ScrollView {
                    VStack(spacing: CicadaTheme.spacingSM) {
                        ForEach(visible) { conversation in
                            ConversationRow(
                                conversation: conversation,
                                onResume: { Task { await act(await viewModel.resume(conversation.id)) } },
                                onCopy: { Task { await act(await viewModel.copyCommand(for: conversation.id)) } },
                                onSelectEntity: onSelectEntity,
                                inSourceList: true
                            )
                        }
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        // G136 R-SU18 — a palette conversation row, until the Reader lands,
        // opens this list filtered to its title.
        .onAppear { if let q = router.consumeConversationQuery() { ownQuery = q; findOpen = true } }
        .onChange(of: router.pendingConversationQuery) { _, _ in
            if let q = router.consumeConversationQuery() { ownQuery = q; findOpen = true }
        }
        // ⌘F opens the list's find while it is closed; once open the field publishes its own (R-SU10).
        .background { Color.clear.publishesPageFind(enabled: !findOpen) { findOpen = true } }
        // Closing find clears it, so a closed find never filters the list out of sight.
        .onChange(of: findOpen) { _, open in if !open { ownQuery = "" } }
        .task {
            guard !loadedOnce else { return }
            loadedOnce = true
            await load()
        }
        .task(id: "\(viewModel.conversations.count)|\(query)") {
            // R-SU22 — debounced like the palette; only a capped page asks.
            // Keyed on the loaded count too: a hand-off sets `query` before
            // the first page lands, and the widening must run once it has.
            try? await Task.sleep(for: SearchTiming.serverDebounce)
            guard !Task.isCancelled else { return }
            await viewModel.searchBeyondCap(query: query, harness: source.harness,
                                            origin: source.harness == nil ? source.origins.first : nil)
        }
    }

    /// Chat exports are harness-kind rows keyed by origin; MCP harnesses by
    /// harness. The overview tells us which filter it wants. The limit is the
    /// backend's own cap (`/conversations/recent` ≤ 200): the filter runs
    /// before it (R5), so this is "everything this source has, up to the cap".
    private func load() async {
        if let harness = source.harness {
            await viewModel.load(limit: ConversationSearch.cap, harness: harness)
        } else {
            await viewModel.load(limit: ConversationSearch.cap, origin: source.origins.first)
        }
    }

    /// Same outcomes as the old ConversationsSection: a clipboard fallback is
    /// never silent; a 409 reloads so the row drops its Resume affordance.
    private func act(_ outcome: ResumeOutcome) async {
        switch outcome {
        case .launched(let app): store.toast = "Reopening in \(app)…"
        case .copied(let command): store.toast = "Copied “\(command)” — paste it into any terminal"
        case .gone:
            store.toast = "That conversation's transcript is gone — nothing to resume"
            await load()
        case .failed(let message): store.toast = message
        }
    }
}
