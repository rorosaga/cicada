import SwiftUI

/// One conversation row: title, harness badge, relative last-write time, an
/// entity-count chip, and a chip per entity that conversation touched. Reused
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
                        .font(CicadaTheme.font(size: 11))
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
            .font(CicadaTheme.font(size: 11))
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
