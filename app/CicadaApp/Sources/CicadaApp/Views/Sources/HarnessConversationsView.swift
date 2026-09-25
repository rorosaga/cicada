import SwiftUI

/// A harness's conversations (G124 §2): title, date, mark, episodes/entities,
/// Resume when the backend says `resumable`, a title filter. Fetched on
/// demand through `/conversations/recent?harness=` (R5) — no Store domain,
/// like the contributor commit drill-down. Resume goes through the existing
/// endpoint: transcripts are never read (G48 — `isfile()` only).
struct HarnessConversationsView: View {
    let source: SourceOverview
    var onSelectEntity: ((String) -> Void)?

    @State private var viewModel = ConversationsViewModel()
    @State private var loadedOnce = false
    @State private var query = ""
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router

    /// R-SU20/R-SU22 — the loaded page filtered in place (newest first, never
    /// re-ranked), then any older matches the capped page could not hold.
    private var visible: [ConversationSummary] {
        ConversationSearch.merge(local: ConversationFilter.apply(viewModel.conversations, query: query),
                                 server: viewModel.beyondCap(for: query))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            CicadaSearchField(text: $query, prompt: "Filter by title")
                .frame(maxWidth: CicadaTheme.scaled(320))
            if let err = viewModel.errorMessage {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    Text(err).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                    Button("Retry") { Task { await load() } }
                        .buttonStyle(.bordered)
                        .accessibilityLabel("Retry loading conversations")
                }
            } else if !viewModel.hasLoaded {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Loading conversations…").font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                }
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
                                onSelectEntity: onSelectEntity
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
        .onAppear { if let q = router.consumeConversationQuery() { query = q } }
        .onChange(of: router.pendingConversationQuery) { _, _ in
            if let q = router.consumeConversationQuery() { query = q }
        }
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
