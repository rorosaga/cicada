import SwiftUI

/// G48 §4 — "Conversations" inside Activity: which conversations wrote to
/// memory, and a way back into the resumable ones.
///
/// On-demand fetch, like `ContributorsSection`'s commit drill-down: no Store
/// domain, no SnapshotCache entry — `.task` loads once per appearance of this
/// view (not per navigation revisit within the same process lifetime, since
/// `loadedOnce` lives on the view's own `@State`).
struct ConversationsSection: View {
    /// Chip tap → the app's existing entity navigation (select in the graph,
    /// switch to it), threaded down from `ContentView` exactly as the Ask
    /// panel's citation taps are. `nil` (the popover) renders inert capsules.
    var onSelectEntity: ((String) -> Void)?

    @State private var viewModel = ConversationsViewModel()
    @State private var loadedOnce = false
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            // Error → never-loaded → loaded-but-empty → list, matching
            // ContributorsSection's loadState shape.
            if let err = viewModel.errorMessage {
                errorState(err)
            } else if !viewModel.hasLoaded {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Loading conversations…")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .frame(maxWidth: .infinity, alignment: .center)
            } else if viewModel.conversations.isEmpty {
                Text(
                    "No conversations yet. They'll show up here once an MCP client "
                    + "saves an episode, or you import a chat export."
                )
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                ScrollView {
                    VStack(spacing: CicadaTheme.spacingSM) {
                        ForEach(viewModel.conversations) { conversation in
                            ConversationRow(
                                conversation: conversation,
                                isSelected: viewModel.selectedId == conversation.id,
                                onResume: { Task { await act(await viewModel.resume(conversation.id)) } },
                                onCopy: { Task { await act(await viewModel.copyCommand(for: conversation.id)) } },
                                onSelectEntity: onSelectEntity
                            )
                        }
                    }
                }
            }

            Spacer()
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        .task {
            guard !loadedOnce else { return }
            loadedOnce = true
            await viewModel.load()
        }
    }

    private func errorState(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(message)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.danger)
            Button("Retry") { Task { await viewModel.load() } }
                .buttonStyle(.bordered)
                .accessibilityLabel("Retry loading conversations")
        }
    }

    /// Report every outcome through the app-wide toast, so a clipboard
    /// fallback is never silent. A 409 also reloads the list so the row that
    /// just failed drops its Resume affordance.
    private func act(_ outcome: ResumeOutcome) async {
        switch outcome {
        case .launched(let app):
            store.toast = "Reopening in \(app)…"
        case .copied(let command):
            store.toast = "Copied “\(command)” — paste it into any terminal"
        case .gone:
            store.toast = "That conversation's transcript is gone — nothing to resume"
            await viewModel.load()
        case .failed(let message):
            store.toast = message
        }
    }
}

/// One conversation row: title, harness badge, relative last-write time, an
/// entity-count chip, and a chip per entity that conversation touched. Reused
/// verbatim by Task 8's popover, so it stays a plain memberwise-initializable
/// type rather than reaching into `ConversationsSection`'s private state.
struct ConversationRow: View {
    let conversation: ConversationSummary
    var isSelected: Bool = false
    let onResume: () -> Void
    let onCopy: () -> Void
    /// Non-nil where the host can navigate to an entity; `nil` in the popover,
    /// where the chips are plain capsules.
    var onSelectEntity: ((String) -> Void)?

    /// How many entity chips one row shows before the rest fold into
    /// "+N more". The backend already caps `entityIds`
    /// (`session_stats.MAX_CONVERSATION_ENTITIES`); this keeps a busy
    /// conversation from turning the row into a wall of capsules.
    static let maxVisibleEntityChips = 6

    /// Pure chip arithmetic, unit-tested — the view body is a thin wrapper.
    /// `hidden` counts BOTH what this row truncates and what the backend
    /// withheld, so "+N more" is measured against the honest `entityCount`.
    static func chipPlan(
        for conversation: ConversationSummary,
        limit: Int = maxVisibleEntityChips
    ) -> (ids: [String], hidden: Int) {
        let ids = Array(conversation.entityIds.prefix(max(0, limit)))
        return (ids, max(0, conversation.entityCount - ids.count))
    }

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            VStack(alignment: .leading, spacing: 4) {
                Text(conversation.displayTitle)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)

                HStack(spacing: CicadaTheme.spacingXS) {
                    badge(harnessLabel)
                    // `model` is a RESERVED wire field — the backend sends null
                    // until engine calls carry session refs (G49), so this
                    // badge is deliberately dormant rather than removed.
                    if let model = conversation.model, !model.isEmpty { badge(model) }
                    Text("\(conversation.episodeCount) episode"
                         + (conversation.episodeCount == 1 ? "" : "s"))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    if conversation.entityCount > 0 {
                        badge("\(conversation.entityCount) entit"
                              + (conversation.entityCount == 1 ? "y" : "ies"))
                    }
                    if let relative = relativeLastSeen {
                        Text(relative)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }

                entityChips
            }

            Spacer(minLength: CicadaTheme.spacingSM)

            if conversation.resumable {
                Menu("Resume") {
                    Button("Resume in terminal", action: onResume)
                    Button("Copy command", action: onCopy)
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                .help("Reopen this conversation with claude --resume")
            }
        }
        .padding(CicadaTheme.spacingSM)
        .background(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .fill(isSelected ? CicadaTheme.surfaceElevated : CicadaTheme.surfaceHover.opacity(0.4))
        )
        .accessibilityElement(children: .contain)
        .accessibilityLabel(
            "\(conversation.displayTitle), \(conversation.episodeCount) episodes"
            + (conversation.resumable ? ", resumable" : "")
        )
    }

    /// The entities this conversation wrote (G48 §4). Tappable where the host
    /// gave us navigation; inert capsules otherwise. Renders nothing at all
    /// when the backend sent no ids, so a pre-G48 row is unchanged.
    @ViewBuilder
    private var entityChips: some View {
        let plan = Self.chipPlan(for: conversation)
        if !plan.ids.isEmpty {
            FlowLayout(spacing: 6) {
                ForEach(plan.ids, id: \.self) { entityChip($0) }
                // Deliberately NOT a button: there is no id behind it to open.
                if plan.hidden > 0 {
                    Text("+\(plan.hidden) more")
                        .font(.system(size: 11))
                        .lineLimit(1)
                        .padding(.horizontal, 8).padding(.vertical, 3)
                        .background(CicadaTheme.surfaceHover)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .clipShape(Capsule())
                        .accessibilityLabel("\(plan.hidden) more entities, not shown")
                }
            }
        }
    }

    @ViewBuilder
    private func entityChip(_ entityId: String) -> some View {
        let label = Text(entityId)
            .font(.system(size: 11))
            .lineLimit(1)
            .padding(.horizontal, 8).padding(.vertical, 3)
            .background(CicadaTheme.accent.opacity(0.10))
            .foregroundStyle(CicadaTheme.accent)
            .clipShape(Capsule())

        if let onSelectEntity {
            Button { onSelectEntity(entityId) } label: { label }
                .buttonStyle(.cicadaPlain)
                .help("Open \(entityId)")
                .accessibilityLabel("Open entity \(entityId)")
        } else {
            label.accessibilityLabel("Entity \(entityId)")
        }
    }

    /// Falls back to the conversation kind when the backend didn't attribute
    /// a harness (e.g. an older episode with no `harness` frontmatter).
    private var harnessLabel: String {
        conversation.harness.isEmpty
            ? (conversation.kind == "import" ? "import" : "conversation")
            : conversation.harness
    }

    /// `nil` when `lastSeen` is empty or unparseable, so the pill is simply
    /// omitted rather than showing a bogus "now".
    private var relativeLastSeen: String? {
        guard let date = Self.parseTimestamp(conversation.lastSeen) else { return nil }
        let fmt = RelativeDateTimeFormatter()
        fmt.unitsStyle = .abbreviated
        return fmt.localizedString(for: date, relativeTo: .now)
    }

    /// The backend emits episode timestamps as ISO-8601, sometimes with
    /// fractional seconds (Anthropic exports carry microseconds). Try the
    /// plain form first, then the fractional-seconds variant.
    private static func parseTimestamp(_ raw: String) -> Date? {
        guard !raw.isEmpty else { return nil }
        if let date = ISO8601DateFormatter().date(from: raw) { return date }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: raw)
    }

    private func badge(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(Capsule().fill(CicadaTheme.surfaceHover))
    }
}
