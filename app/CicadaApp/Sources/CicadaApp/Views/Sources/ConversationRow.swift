import SwiftUI

/// One conversation row: title, harness badge, relative last-write time, a
/// page count, and a named `Tag` per page that conversation touched. Reused
/// verbatim by `ConversationPopover` and, since G124, by a harness page
/// (`HarnessConversationsView`), so it stays a plain memberwise-initializable
/// type rather than reaching into `ConversationsSection`'s private state.
struct ConversationRow: View {
    let conversation: ConversationSummary
    var isSelected: Bool = false
    let onResume: () -> Void
    let onCopy: () -> Void
    /// Non-nil where the host can navigate to an entity; `nil` in the popover,
    /// where the chips are plain capsules.
    var onSelectEntity: ((String) -> Void)?
    /// Sources v4 (owner 2026-10-19: each row repeated "claude-code · 1 episode") — inside one harness's own list the
    /// harness is the page's header and a session is one episode (G104), so the row says neither: its title, its age
    /// and the pages it wrote. The popover, which mixes harnesses, keeps both.
    var inSourceList = false

    /// The graph's names, so a page this conversation wrote reads as its name, never its id (DR-54, DR-56; as Past
    /// reads' run detail does); optional for the popover's and previews' hosts.
    @Environment(Store.self) private var store: Store?

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
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(conversation.displayTitle)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)

                HStack(spacing: CicadaTheme.spacingXS) {
                    if !inSourceList { badge(harnessLabel) }
                    // `model` is a RESERVED wire field — the backend sends null
                    // until engine calls carry session refs (G49), so this
                    // badge is deliberately dormant rather than removed.
                    if let model = conversation.model, !model.isEmpty { badge(model) }
                    // The row is one conversation; `episodeCount` is how many times it was saved (its capture plus
                    // what the agent saved in it) — said that way, never as "episodes" (ruling 39).
                    if !inSourceList || conversation.episodeCount > 1 {
                        Text(Copy.conversationSaved(conversation.episodeCount))
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                    if conversation.entityCount > 0 && !inSourceList {
                        badge(Copy.conversationPages(conversation.entityCount))
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
            CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(isSelected ? CicadaTheme.surfaceElevated : CicadaTheme.surfaceHover.opacity(0.4))
        )
        .accessibilityElement(children: .contain)
        .accessibilityLabel(
            "\(conversation.displayTitle), \(Copy.conversationSaved(conversation.episodeCount).lowercased())"
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
                    Text("+\(UsageFormat.count(plan.hidden)) more")
                        .font(CicadaTheme.metaFont)
                        .lineLimit(1)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .accessibilityLabel("\(UsageFormat.count(plan.hidden)) more pages, not shown")
                }
            }
        }
    }

    @ViewBuilder
    /// A page as a neutral `Tag` with its name (DR-5: the accent is not a tag's colour; DR-44, DR-54), the id only in
    /// `.help` — the same chip Past reads' run detail draws.
    private func entityChip(_ entityId: String) -> some View {
        let name = Self.pageLabel(entityId, names: store?.entityNames ?? .empty)
        let label = Tag(text: name).lineLimit(1)

        return Group {
            if let onSelectEntity {
                Button { onSelectEntity(entityId) } label: { label }
                    .buttonStyle(.cicadaPlain)
                    .accessibilityLabel("Open \(name)")
            } else {
                label.accessibilityLabel(name)
            }
        }
        .help(entityId)
    }

    /// A page id as its page's name; an id the graph does not hold stays as it is (`EntityNames.display`).
    static func pageLabel(_ id: String, names: EntityNames) -> String { names.display(id) }

    /// The harness by the name a person uses (DR-54, "Claude Code", never `claude-code`); the conversation's kind when
    /// the backend didn't attribute one (an older episode with no `harness` frontmatter).
    private var harnessLabel: String {
        conversation.harness.isEmpty
            ? (conversation.kind == "import" ? "Import" : "Conversation")
            : OriginIconography.label(for: conversation.harness)
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
