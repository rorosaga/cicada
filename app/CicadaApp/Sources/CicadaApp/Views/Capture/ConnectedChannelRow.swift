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

    @Environment(BrowserWatcher.self) private var watcher
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
    /// logo load, not "working"); otherwise a channel with a brand mark gets
    /// the Linear-style tile, and everything else keeps the original
    /// tint-circle + SF Symbol treatment.
    ///
    /// R6 — one precedence, three surfaces: the tile is taken when EITHER
    /// rung exists, because Safari and Apple Notes have an installed-app icon
    /// and no bundled PNG (R2 forbids theirs). Keying only on `logoName`
    /// would draw a tint circle here where the Sleep desk draws the app's own
    /// icon.
    @ViewBuilder
    private var rowIcon: some View {
        let logoName = Self.logoName(for: channel.id)
        let bundleId = OriginIconography.appBundleId(for: Self.origin(forChannel: channel.id))
        if isBusy {
            ZStack {
                Circle()
                    .fill(Self.tint(for: channel.id).opacity(0.12))
                    .overlay(Circle().stroke(CicadaTheme.border, lineWidth: 1))
                ProgressView().controlSize(.small)
            }
            .frame(width: 28, height: 28)
        } else if logoName != nil || bundleId != nil {
            LogoImage.platformTile(name: logoName ?? "", bundleId: bundleId, size: 28,
                                   systemFallback: Self.icon(for: channel.id))
        } else {
            ZStack {
                Circle()
                    .fill(Self.tint(for: channel.id).opacity(0.12))
                    .overlay(Circle().stroke(CicadaTheme.border, lineWidth: 1))
                Image(systemName: Self.icon(for: channel.id))
                    .font(CicadaTheme.font(size: 13, weight: .medium))
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
                        HStack(spacing: CicadaTheme.spacingXS) {
                            Text(channel.label)
                                .font(CicadaTheme.font(size: 13, weight: .medium))
                                .foregroundStyle(CicadaTheme.textPrimary)
                            // G129: a watched browser wears its light here
                            // too, so "is this live" is answerable from the
                            // Feed without opening the source page. Compact —
                            // the dot only; the sentence lives on that page.
                            if let watchState = watcher.state(for: channel.id) {
                                BrowserStatusLight(state: watchState,
                                                   error: watcher.error(for: channel.id),
                                                   compact: true)
                            }
                        }
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
                .font(CicadaTheme.font(size: 10, weight: .semibold))
                .foregroundStyle(CicadaTheme.textTertiary)
                .opacity(isHovered ? 1 : 0)
                .accessibilityHidden(true)

            Menu {
                ForEach(Self.menuActions(for: channel), id: \.self) { action in
                    Button(Self.actionTitle(action, channel: channel)) { onAction(action) }
                }
            } label: {
                Image(systemName: "ellipsis")
                    .font(CicadaTheme.font(size: 12, weight: .semibold))
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
    ///
    /// R7 — `icon`/`tint` deliberately do NOT delegate to `OriginIconography`
    /// the way `logoName` now does. They are the fallback circle's own
    /// palette, already non-`tray` for every channel id
    /// (`ChannelMarkTests.testNoChannelFallsThroughToTheGenericTray`), and
    /// routing them through the origin map would silently change `files` from
    /// `link` to `bookmark.fill` for no gain.
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

    /// The origin id the backend's own catalog gives this channel —
    /// `source_overview.SourceSpec.mark`, mirrored (R-L4). The channel id
    /// space (`chrome-bookmarks`, what the user connects) and the origin id
    /// space (`chrome-bookmark`, what an episode is stamped with) are not the
    /// same strings, so this function is the seam that lets one map answer
    /// both.
    ///
    /// Total on purpose: an id the backend adds before this switch does
    /// resolves to itself rather than trapping, and
    /// `ChannelMarkTests.testNoChannelFallsThroughToTheGenericTray` is what
    /// makes the missing row loud instead of silent.
    static func origin(forChannel id: String) -> String {
        switch id {
        case "chat-export:claude": "claude-export"
        case "chat-export:chatgpt": "chatgpt-export"
        case "chrome-bookmarks": "chrome-bookmark"
        case "safari-bookmarks": "safari-bookmark"
        case "safari-tabs": "safari-tab"
        case "notes": "apple-notes"
        case "reddit": "reddit-saved"
        case "x": "x-bookmarks"
        // `files` is `bookmark`, not `saved-link`: `saved-link` is in that
        // row's `origins` tuple, while `mark` — the column the app reads — is
        // `bookmark`.
        case "files": "bookmark"
        // `rss`, `calendar`, `pinterest`, `telegram` name themselves.
        default: id
        }
    }

    /// The bundled brand mark for a channel — one line, because
    /// `OriginIconography.logoName` is the only id → asset map there is
    /// (R-L4). This used to be a second, shorter switch returning only
    /// `pinterest|reddit|x|telegram`, which is why Chrome was a plain blue
    /// globe in Settings → Integrations while being a drawn glyph on the
    /// Sleep desk, and why the two chat exports rendered as one shared SF
    /// bubble: one source, three pictures.
    static func logoName(for id: String) -> String? {
        OriginIconography.logoName(for: origin(forChannel: id))
    }
}
