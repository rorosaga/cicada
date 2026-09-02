import SwiftUI

/// A transient one-line result under the channel list ("3 new items", or an
/// error). `Equatable` so the view can key a `.task(id:)` on it and restart
/// the auto-clear when a second result lands.
struct ChannelFeedback: Equatable {
    let text: String
    let isError: Bool
}

/// One connected capture channel (G62): a 28-pt circular icon, the channel
/// label, the server's own `detail` line, and a trailing ⋯ menu carrying
/// exactly the actions the backend said this channel supports.
///
/// The whole row is a `Button` (opens "Manage…") so VoiceOver and UI automation
/// can reach it; the ⋯ menu is a second, separately-labelled control.
struct ConnectedChannelRow: View {
    let channel: SourceChannel
    /// True while this row's own poll/sync is in flight — the icon becomes a
    /// spinner so the feedback is attached to the row that caused it, not to
    /// the page.
    var isBusy: Bool = false
    /// PR #19 round-4 review: this row's own result line, owned by the row
    /// (not a single page-wide slot in `ConnectedChannelsStrip`) — two rows
    /// acting concurrently used to share one `feedback: ChannelFeedback?`,
    /// so whichever finished last replaced (or cleared) the other's still-
    /// relevant result. A `Binding` into the parent's per-channel-id
    /// dictionary keeps this row's 5 s auto-clear (below) from ever touching
    /// another row's slot. `.constant(nil)` default keeps every other/no
    /// call site (and any future one) source-compatible.
    var feedback: Binding<ChannelFeedback?> = .constant(nil)
    /// Receives an action id from `menuActions(for:)`, or `"manage"` when the
    /// row itself is activated.
    let onAction: (String) -> Void

    @State private var isHovered = false

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            rowContent
            // PR #19 round-4 review: owned by this row (via the `feedback`
            // binding into the parent's per-channel dictionary) so a second
            // row's action completing — in either order — can never clear or
            // replace this one's result. Mirrors the page-level 5 s
            // auto-clear this pattern was lifted from (SourcesView's fix),
            // just scoped to one row instead of the whole strip.
            if let value = feedback.wrappedValue {
                Text(value.text)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(value.isError ? CicadaTheme.danger : CicadaTheme.success)
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .task(id: value) {
                        try? await Task.sleep(for: .seconds(5))
                        guard !Task.isCancelled else { return }
                        feedback.wrappedValue = nil
                    }
            }
        }
    }

    /// The row's leading 28pt icon. A busy row always shows the plain
    /// circle+spinner (a platform tile mid-spin would look like a broken
    /// logo load, not "working"); otherwise a channel with a bundled brand
    /// mark (Task 13) gets the Linear-style tile, and everything else keeps
    /// the original tint-circle + SF Symbol treatment.
    @ViewBuilder
    private var rowIcon: some View {
        if isBusy {
            ZStack {
                Circle()
                    .fill(Self.tint(for: channel.id).opacity(0.12))
                    .overlay(Circle().stroke(CicadaTheme.border, lineWidth: 1))
                ProgressView().controlSize(.small)
            }
            .frame(width: 28, height: 28)
        } else if let logoName = Self.logoName(for: channel.id) {
            LogoImage.platformTile(name: logoName, size: 28, systemFallback: Self.icon(for: channel.id))
        } else {
            ZStack {
                Circle()
                    .fill(Self.tint(for: channel.id).opacity(0.12))
                    .overlay(Circle().stroke(CicadaTheme.border, lineWidth: 1))
                Image(systemName: Self.icon(for: channel.id))
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Self.tint(for: channel.id))
            }
            .frame(width: 28, height: 28)
        }
    }

    private var rowContent: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            Button { onAction("manage") } label: {
                HStack(spacing: CicadaTheme.spacingMD) {
                    rowIcon

                    VStack(alignment: .leading, spacing: 2) {
                        Text(channel.label)
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                        if let detail = channel.detail {
                            Text(detail)
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .lineLimit(1)
                        }
                    }
                    Spacer()
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(channel.detail.map { "\(channel.label). \($0)" } ?? channel.label)

            Image(systemName: "chevron.right")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(CicadaTheme.textTertiary)
                .opacity(isHovered ? 1 : 0)
                .accessibilityHidden(true)

            Menu {
                ForEach(Self.menuActions(for: channel), id: \.self) { action in
                    Button(Self.actionTitle(action, channel: channel)) { onAction(action) }
                }
            } label: {
                Image(systemName: "ellipsis")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .frame(width: 24, height: 24)
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .frame(width: 24)
            .disabled(isBusy)
            .accessibilityLabel("Actions for \(channel.label)")
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .background(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .fill(isHovered ? CicadaTheme.surfaceHover : .clear)
        )
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.12), value: isHovered)
    }

    /// The backend lists what a channel supports; "Manage…" is appended
    /// regardless (and de-duplicated), because tapping the row already opens
    /// it and nothing on screen advertised that. "remove" is dropped: nothing
    /// implements it — it was routed to the same manage sheet as everything
    /// else, so the item lied about what it did.
    static func menuActions(for channel: SourceChannel) -> [String] {
        channel.actions.filter { $0 != "manage" && $0 != "remove" } + ["manage"]
    }

    static func actionTitle(_ action: String, channel: SourceChannel) -> String {
        switch action {
        case "poll": "Poll now"
        case "sync": "Sync now"
        case "manage": "Manage…"
        case "import": "Import another file…"
        default: action.capitalized
        }
    }

    /// Icons/tints mirror `OriginPill` so a channel and its origin pill read as
    /// the same thing on the same page.
    static func icon(for id: String) -> String {
        switch id {
        case "rss": "dot.radiowaves.up.forward"
        case "calendar": "calendar"
        case "chrome-bookmarks": "globe"
        case "safari-bookmarks", "safari-tabs": "safari"
        case "notes": "note.text"
        case "telegram": "paperplane.fill"
        case "chat-export:claude", "chat-export:chatgpt": "bubble.left.and.bubble.right"
        case "files": "link"
        case "pinterest": "pin.fill"
        case "reddit": "bubble.left.and.text.bubble.right.fill"
        case "x": "x.circle"
        default: "tray"
        }
    }

    static func tint(for id: String) -> Color {
        switch id {
        case "rss": Color(hex: 0xEE802F)
        case "calendar": Color(hex: 0xFF3B30)
        // R4 — one row per browser, tinted like its `OriginIconography` origin.
        case "chrome-bookmarks": Color(hex: 0x4285F4)
        case "safari-bookmarks", "safari-tabs": Color(hex: 0x00A2E8)
        case "notes": Color(hex: 0xFFCC00)
        case "telegram": Color(hex: 0x26A5E4)
        case "chat-export:claude", "chat-export:chatgpt": CicadaTheme.accent
        case "files": Color(hex: 0x8896FF)
        case "pinterest": Color(hex: 0xE60023)
        case "reddit": Color(hex: 0xFF4500)
        default: CicadaTheme.textSecondary
        }
    }

    /// Task 13 — the bundled brand-mark PNG for a connector-backed channel
    /// (Pinterest, Reddit, X, Telegram; `AddSourceTile.logoName` is the same
    /// mapping on the catalog side). Every other channel id keeps its SF
    /// Symbol circle — no single brand mark exists for a bookmarks sync that
    /// reads both Chrome and Safari, or for a multi-vendor chat export.
    static func logoName(for id: String) -> String? {
        switch id {
        case "pinterest": "pinterest"
        case "reddit": "reddit"
        case "x": "x"
        case "telegram": "telegram"
        default: nil
        }
    }
}
