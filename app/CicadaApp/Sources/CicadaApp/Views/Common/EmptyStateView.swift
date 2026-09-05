import SwiftUI

/// G117 — one honest "nothing here, here's the one thing to do" component,
/// reused by every tab that can be empty on a fresh bank (Graph, Inbox,
/// Feed, Sources — Sleep's own desk already handles zero, G125). The
/// bookworm at `.happy` reads as reassurance, not an error.
///
/// Two action shapes, not one, because a PLAIN closure cannot reliably open
/// the Settings window on this app's target OS — the reasoning, and the one
/// writer of the section seed, now live in `SettingsSectionLink` (G125 v3,
/// P5), which this view renders when `settingsSection` is set. The moment ANY
/// empty state needs to send the person to Settings, it must go through that
/// view, never a bare `action:` closure that calls `openSettings()` or the
/// private AppKit selector directly.
struct EmptyStateView: View {
    let title: String
    let message: String
    var actionLabel: String? = nil
    var action: (() -> Void)? = nil
    /// Set instead of `actionLabel`/`action` when the one thing to do is
    /// "open Settings, on this section."
    var settingsSection: SettingsSection? = nil

    var body: some View {
        VStack(spacing: CicadaTheme.spacingLG) {
            BookwormView(state: .happy, pointSize: 96)
            Text(title).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
            Text(message)
                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            if let section = settingsSection, let actionLabel {
                SettingsSectionLink(section: section, label: actionLabel)
            } else if let actionLabel, let action {
                Button(actionLabel, action: action)
                    .buttonStyle(.cicadaPlain).foregroundStyle(CicadaTheme.accent)
            }
        }
        .frame(maxWidth: 360)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
