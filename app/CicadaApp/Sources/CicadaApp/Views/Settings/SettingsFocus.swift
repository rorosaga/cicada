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

    /// The row a landing keeps on screen while the page's late cards arrive (`CicadaMotion.settingsLandingWindow`).
    /// `settleNonce` asks `SettingsScroll` to land on it again; nil once the person takes over or the window ends.
    private(set) var settling: SettingsRowID?
    private(set) var settleNonce = 0
    private var settleUntil = Date.distantPast
    private var settledY: CGFloat?
    private var personMonitor: Any?

    func go(_ section: SettingsSection, row: SettingsRowID? = nil) {
        requests &+= 1
        request = Request(section: section, row: row, nonce: requests)
    }

    func land(on row: SettingsRowID, announcing name: String, reduceMotion: Bool, now: Date = Date()) {
        beginSettle(row, now: now)
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

    // MARK: Keeping a landed row on screen

    /// The settling row's top in its scroll content's own space: only layout moves it there, never a scroll. Its first
    /// report (the row may not have existed at the first scroll) and every change inside the window land again.
    func settlingRowMoved(_ row: SettingsRowID, contentY: CGFloat, now: Date = Date()) {
        guard row == settling else { return }
        guard now < settleUntil else { endSettle(); return }
        guard contentY != settledY else { return }
        settledY = contentY
        settleNonce &+= 1
    }

    /// The person scrolled, typed a search or picked another page: the landing is theirs to leave.
    func endSettle() {
        settling = nil
        settledY = nil
        if let monitor = personMonitor { NSEvent.removeMonitor(monitor) }
        personMonitor = nil
    }

    private func beginSettle(_ row: SettingsRowID, now: Date) {
        endSettle()
        settling = row
        settleUntil = now.addingTimeInterval(CicadaMotion.settingsLandingWindow)
        // A scroll wheel, trackpad or key is the person's: a programmatic `scrollTo` sends none of these. `NSApp` is
        // read as a global so a headless `swift test` never creates the app (the same rule as the announcement).
        guard NSApp != nil else { return }
        personMonitor = NSEvent.addLocalMonitorForEvents(matching: [.scrollWheel, .keyDown]) { [weak self] event in
            self?.endSettle()
            return event
        }
    }
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
            .onGeometryChange(for: CGFloat.self) { $0.frame(in: .named(SettingsScrollSpace.content)).minY } action: { y in
                guard let focus, focus.settling == id else { return }
                focus.settlingRowMoved(id, contentY: y)
            }
    }
}

extension View {
    func settingsRow(_ id: SettingsRowID) -> some View { modifier(SettingsRowAnchor(id: id)) }
}

/// The scroll content's own space (rows report their place in it while a landing settles) and the visible one.
enum SettingsScrollSpace {
    static let content = "settings.scroll.content"
    static let viewport = "settings.scroll.viewport"
}

/// A Settings page's one scroll view: scrolls to the focus's target after
/// layout, then consumes it.
struct SettingsScroll<Content: View>: View {
    @Environment(SettingsFocus.self) private var focus: SettingsFocus?
    @State private var viewportHeight: CGFloat = 0
    @ViewBuilder var content: () -> Content

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView { content().coordinateSpace(name: SettingsScrollSpace.content) }
                .coordinateSpace(name: SettingsScrollSpace.viewport)
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { viewportHeight = $0 }
                .environment(\.settingsViewportHeight, viewportHeight)
                .onAppear { scroll(proxy) }
                .onChange(of: focus?.scrollNonce ?? 0) { _, _ in scroll(proxy) }
                // Never animated: a landing is often a keyboard action (DR-60).
                .onChange(of: focus?.settleNonce ?? 0) { _, _ in
                    if let row = focus?.settling { proxy.scrollTo(row, anchor: .center) }
                }
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

/// The visible height of the page's scroll view, for a group that acts only once it is on screen (From anywhere's
/// reachability probe). Zero outside a `SettingsScroll`.
private struct SettingsViewportHeightKey: EnvironmentKey { static let defaultValue: CGFloat = 0 }
extension EnvironmentValues {
    var settingsViewportHeight: CGFloat {
        get { self[SettingsViewportHeightKey.self] }
        set { self[SettingsViewportHeightKey.self] = newValue }
    }
}
