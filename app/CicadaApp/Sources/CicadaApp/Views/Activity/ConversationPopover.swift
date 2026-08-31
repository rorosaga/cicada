import SwiftUI

/// G48 §4 — "open the conversation that wrote this", from an entity-history
/// row or a contributor commit.
///
/// DEVIATION FROM THE SPEC (recorded deliberately): the spec described landing
/// on Activity ▸ Conversations with the row selected. `selectedTab` is `@State`
/// in `ContentView` threaded by `@Binding`, and both `ContentView.swift` and
/// `SidebarView.swift` were being rewritten by the UI round when this shipped,
/// so the conversation is shown IN PLACE instead — same row, same Resume menu,
/// no edits to files under concurrent rewrite. Cross-tab focus is a later
/// refinement, not a missing capability.
struct ConversationPopover: View {
    let sessionIds: [String]

    @State private var viewModel = ConversationsViewModel()
    @State private var loadedOnce = false
    @Environment(Store.self) private var store

    private var known: [ConversationSummary] {
        sessionIds.compactMap { viewModel.conversation(id: $0) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("Written by")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)

            if !viewModel.hasLoaded {
                ProgressView().controlSize(.small)
            } else if known.isEmpty {
                Text("This bank no longer has episodes for that conversation.")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            } else {
                ForEach(known) { conversation in
                    ConversationRow(
                        conversation: conversation,
                        onResume: { Task { await act(await viewModel.resume(conversation.id)) } },
                        onCopy: { Task { await act(await viewModel.copyCommand(for: conversation.id)) } }
                    )
                }
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: 420)
        .task {
            guard !loadedOnce else { return }
            loadedOnce = true
            await viewModel.load(limit: 200)
        }
    }

    private func act(_ outcome: ResumeOutcome) async {
        switch outcome {
        case .launched(let app): store.toast = "Reopening in \(app)…"
        case .copied(let command): store.toast = "Copied “\(command)”"
        case .gone: store.toast = "That conversation's transcript is gone — nothing to resume"
        case .failed(let message): store.toast = message
        }
    }
}

/// The row-level trigger. Renders NOTHING when there is no conversation behind
/// the commit, so every pre-G48 row looks exactly as it did.
struct FromConversationButton: View {
    let sessionIds: [String]

    @State private var isPresented = false

    /// Pure predicate, unit-tested — the view body is a thin wrapper over it.
    static func shouldRender(sessionIds: [String]) -> Bool { !sessionIds.isEmpty }

    var body: some View {
        if Self.shouldRender(sessionIds: sessionIds) {
            Button {
                isPresented = true
            } label: {
                Label("from conversation", systemImage: "bubble.left.and.bubble.right")
                    .font(CicadaTheme.captionFont)
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(.plain)
            .foregroundStyle(CicadaTheme.textSecondary)
            .help("Show the conversation that wrote this, and reopen it")
            .accessibilityLabel("Show the conversation that wrote this")
            .popover(isPresented: $isPresented, arrowEdge: .bottom) {
                ConversationPopover(sessionIds: sessionIds)
            }
        }
    }
}
