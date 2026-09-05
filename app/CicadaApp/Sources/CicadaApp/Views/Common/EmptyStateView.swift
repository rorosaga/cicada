import SwiftUI

/// G117 — one honest "nothing here, here's the one thing to do" component,
/// reused by every tab that can be empty on a fresh bank (Graph, Inbox,
/// Feed, Sources — Sleep's own desk already handles zero, G125). The
/// bookworm at `.happy` reads as reassurance, not an error.
///
/// Two action shapes, not one, because a PLAIN closure cannot reliably open
/// the Settings window on this app's target OS: `SidebarView.swift`'s own
/// `SettingsGearButton` docstring records measuring the private AppKit
/// window-opening selector as *accepted and silently ignored* on macOS 26 —
/// `NSApp.sendAction` returns `true`, no window appears — which is why that
/// button is built from `SettingsLink` (a `View`, not a callable action)
/// rather than a `Button` with an imperative body (see
/// `SettingsEntryPointTests.testNoPrivateSettingsSelector`, which fails the
/// build on that selector literal reappearing anywhere in `Sources/`).
/// `settingsSection` renders that same `SettingsLink`, pre-seeding which
/// section it opens to via a `.simultaneousGesture` (runs alongside
/// `SettingsLink`'s own built-in action, not instead of it) — the moment ANY
/// empty state needs to send the person to Settings, it must use this path,
/// never a bare `action:` closure that calls `openSettings()` or the AppKit
/// selector directly.
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
                SettingsLink { Text(actionLabel) }
                    .buttonStyle(.cicadaPlain).foregroundStyle(CicadaTheme.accent)
                    // Seeds the section `SettingsScene.onAppear` reads
                    // (`:19,34` — the same `@AppStorage("cicada.settingsSection")`
                    // key it already persists to) BEFORE the link's own
                    // built-in action opens the window, so it opens
                    // straight to the intended section instead of wherever
                    // Settings was last left.
                    .simultaneousGesture(TapGesture().onEnded {
                        UserDefaults.standard.set(section.rawValue, forKey: "cicada.settingsSection")
                    })
            } else if let actionLabel, let action {
                Button(actionLabel, action: action)
                    .buttonStyle(.cicadaPlain).foregroundStyle(CicadaTheme.accent)
            }
        }
        .frame(maxWidth: 360)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
