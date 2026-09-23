import AppKit
import SwiftUI

/// Landing on a row (G139, design §2.4): navigate, scroll, wash, announce —
/// one object per Settings panel, handed down the environment, so a row
/// anywhere can be reached without the page knowing who asked. Search hits,
/// deep links (`SettingsSectionLink(section:row:)`, through
/// `AppRouter.openSettings`) and in-panel pointers (`SettingsInlineLink`) all
/// end in `go(_:row:)`; the panel applies the section, then calls `land(on:…)`.
@Observable
@MainActor
final class SettingsFocus {
    struct Request: Equatable {
        let section: SettingsSection
        let row: SettingsRowID?
        let nonce: Int
    }

    private(set) var request: Request?
    private(set) var scrollTarget: SettingsRowID?
    private(set) var scrollNonce = 0
    private(set) var highlighted: SettingsRowID?
    /// The last row landed on, for a page that reacts to it (Agents opens the
    /// landed agent's disclosure, R-O11).
    private(set) var landed: SettingsRowID?
    private(set) var landedNonce = 0
    /// Rows matching an active query carry a steady 3 pt leading bar (§2.4).
    var matchedRows: Set<SettingsRowID> = []
    /// A sub-page's "go back", taken by Esc before the panel's close (R-O5:
    /// "⌘[ and Esc go back"; DS-1 final review). The panel's × carries a
    /// window-wide `.cancelAction`, and AppKit resolves that key equivalent
    /// before a view's `.onExitCommand` ever sees `cancelOperation:` — so a
    /// sub-page's own exit command would never fire and Esc would close the
    /// whole panel, losing the open detail. One owner of Esc, one check here.
    var escapeBack: (() -> Void)?

    /// What Esc (or the ×'s key equivalent) does right now: back out of an
    /// open sub-page first, and only close the panel from a top-level page.
    func escape(close: () -> Void) {
        if let back = escapeBack { back() } else { close() }
    }

    private var requests = 0
    private var fade: Task<Void, Never>?

    func go(_ section: SettingsSection, row: SettingsRowID? = nil) {
        requests &+= 1
        request = Request(section: section, row: row, nonce: requests)
    }

    func land(on row: SettingsRowID, announcing name: String, reduceMotion: Bool) {
        scrollTarget = row
        scrollNonce &+= 1
        landed = row
        landedNonce &+= 1
        highlighted = row
        // `AppRouter.activateMainWindow`'s rule: read the `NSApp` global (which
        // never creates the app) so `SettingsKitTests` — a headless `swift test`
        // process — lands a row without instantiating NSApplication.
        if NSApp != nil { AccessibilityNotification.Announcement(name).post() }
        fade?.cancel()
        fade = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(CicadaMotion.rowHighlightHold))
            // R-O7: under Reduce Motion the fade's time is spent holding instead.
            if reduceMotion { try? await Task.sleep(for: .seconds(CicadaMotion.rowHighlightFadeDuration)) }
            guard !Task.isCancelled, let self else { return }
            withAnimation(CicadaMotion.rowHighlightFade(reduceMotion: reduceMotion)) { self.highlighted = nil }
        }
    }

    /// Called by the page's `SettingsScroll` once it has scrolled.
    func consumeScroll() { scrollTarget = nil }
}

/// What makes a view a landing place (R-O6): an id for `ScrollViewReader`, an
/// AX identifier for `macos-harness`, the landing wash and the match bar. Inert
/// where no `SettingsFocus` is in the environment (onboarding embeds).
struct SettingsRowAnchor: ViewModifier {
    let id: SettingsRowID
    @Environment(SettingsFocus.self) private var focus: SettingsFocus?
    @Environment(\.colorSchemeContrast) private var contrast

    func body(content: Content) -> some View {
        content
            .background {
                if focus?.highlighted == id {
                    // DR-33 / R-DS26 — a landed row: the selected fill and the focus ring (DR-5
                    // use 1), never a nature wash on a row (DR-13).
                    CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                        .fill(CicadaTheme.bgSelected)
                        .overlay(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                            .strokeBorder(contrast == .increased ? CicadaTheme.textPrimary : CicadaTheme.focusRing,
                                          lineWidth: 2))
                        .transition(.opacity)
                }
            }
            .overlay(alignment: .leading) {
                // A match is a neutral bar, not a colour (DR-13): the query already says why.
                if focus?.matchedRows.contains(id) == true {
                    Rectangle().fill(CicadaTheme.textTertiary).frame(width: 3)
                }
            }
            .id(id)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("settings.row.\(id.rawValue)")
    }
}

extension View {
    func settingsRow(_ id: SettingsRowID) -> some View { modifier(SettingsRowAnchor(id: id)) }
}

/// A Settings page's one scroll view: scrolls to the focus's target after
/// layout, then consumes it.
struct SettingsScroll<Content: View>: View {
    @Environment(SettingsFocus.self) private var focus: SettingsFocus?
    @ViewBuilder var content: () -> Content

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView { content() }
                .onAppear { scroll(proxy) }
                .onChange(of: focus?.scrollNonce ?? 0) { _, _ in scroll(proxy) }
        }
    }

    private func scroll(_ proxy: ScrollViewProxy) {
        guard let focus, let target = focus.scrollTarget else { return }
        Task { @MainActor in
            await Task.yield()   // after this layout pass, so the row exists
            proxy.scrollTo(target, anchor: .center)
            focus.consumeScroll()
        }
    }
}
