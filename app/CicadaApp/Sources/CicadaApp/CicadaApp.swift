import SwiftUI
import AppKit

/// A transparent AppKit passthrough container that accepts the first mouse
/// click even when its window isn't key yet. `ClickableWebView`
/// (`Views/Graph/GraphView.swift`) already opts into this per-instance for
/// the graph canvas, but plain SwiftUI controls (Button, Toggle, etc.) render
/// inside the framework's own NSHostingView, whose `acceptsFirstMouse(for:)`
/// defaults to `false` — so the very first click on any native control after
/// the app loses focus is consumed as mere window activation instead of
/// reaching the control ("needs a second click" bug). Wrapping the SwiftUI
/// content view once, at the window level, fixes this for every control
/// without touching each one individually.
final class FirstMouseAcceptingView: NSView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

@main
struct CicadaApp: App {
    /// Single source of truth for every screen (§5.1). Hydrated from disk on
    /// appear, then kept live by its `SyncEngine`. Every view model below is
    /// constructed in `init()` as a thin projection over this same instance
    /// (§5.5) rather than fetching independently.
    @State private var store: Store
    @State private var graphVM: GraphViewModel
    @State private var inboxVM: InboxViewModel
    @State private var sleepVM: SleepViewModel
    /// G122: Settings → Sleep's engine-and-model picker. No `Store`
    /// dependency (ruling 6 — a plain `APIClient` round trip, nothing else
    /// observes this domain) — constructed bare, unlike every view model
    /// above it.
    @State private var sleepEngineVM = SleepEngineViewModel()
    @State private var banksVM: BanksViewModel
    @State private var feedVM: FeedViewModel
    @State private var contributorsVM: ContributorsViewModel
    @State private var connectionsVM: ConnectionsViewModel
    @State private var usageVM: UsageViewModel
    @State private var menuBarManager = MenuBarManager()
    @State private var backend = BackendProcess()
    /// G129: a bookmark saved in Chrome or Safari reaches the queue in seconds
    /// without a button. App-side because the launchd backend has no Full Disk
    /// Access — see `BrowserWatch.swift`.
    @State private var browserWatcher = BrowserWatcher()
    /// G130: the local key monitor that routes ⌘⇧= to `CicadaTheme.zoomIn()`
    /// (see `ZoomKeyRouter`). Held so `.onAppear` (which can fire again —
    /// see `enableFirstMouseAcceptance`'s own idempotence note below) never
    /// installs a second monitor and double-fires every zoom keystroke.
    @State private var zoomMonitor: Any?

    // Theme: persisted mode driving both the SwiftUI environment
    // (`.preferredColorScheme`, so system materials/controls follow) and the
    // native AppKit window chrome (titlebar/background), which NSWindow
    // doesn't pick up from SwiftUI state automatically — see
    // `syncWindowChrome` below.
    @AppStorage("cicada.colorScheme") private var colorSchemeRaw: String = AppColorScheme.dark.rawValue
    private var appColorScheme: AppColorScheme { AppColorScheme(rawValue: colorSchemeRaw) ?? .dark }

    init() {
        // Swift Package executable targets launch without an Info.plist, so AppKit
        // treats the process as a command-line tool by default. The window appears
        // but is never made *key*, which means TextFields can never become first
        // responder — that's the "can't type in the search/clarification fields"
        // bug. Explicitly requesting .regular activation fixes it.
        NSApplication.shared.setActivationPolicy(.regular)
        NSApplication.shared.activate(ignoringOtherApps: true)

        // Build the Store as a plain local value first — referencing `self`
        // (which `store` would, via the property wrapper) isn't allowed yet
        // because the view-model `@State` properties below aren't
        // initialised. Every view model is then constructed as a thin
        // projection over that single Store (§5.5) instead of fetching
        // independently.
        let store = Store()
        _store = State(initialValue: store)
        _graphVM = State(initialValue: GraphViewModel(store: store))
        _inboxVM = State(initialValue: InboxViewModel(store: store))
        _sleepVM = State(initialValue: SleepViewModel(store: store))
        _banksVM = State(initialValue: BanksViewModel(store: store))
        _feedVM = State(initialValue: FeedViewModel(store: store))
        _contributorsVM = State(initialValue: ContributorsViewModel(store: store))
        _connectionsVM = State(initialValue: ConnectionsViewModel(store: store))
        _usageVM = State(initialValue: UsageViewModel(store: store))
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(graphVM)
                .environment(inboxVM)
                .environment(sleepVM)
                .environment(sleepEngineVM)
                .environment(banksVM)
                .environment(feedVM)
                .environment(contributorsVM)
                .environment(connectionsVM)
                .environment(usageVM)
                .environment(store)
                .environment(browserWatcher)
                .preferredColorScheme(appColorScheme == .light ? .light : .dark)
                .onChange(of: colorSchemeRaw) { _, newValue in
                    let mode = AppColorScheme(rawValue: newValue) ?? .dark
                    CicadaTheme.mode = mode
                    if let window = NSApplication.shared.windows.first(where: { $0.canBecomeKey }) {
                        syncWindowChrome(window, mode: mode)
                    }
                }
                .onAppear {
                    // G130 R5: the View menu's CommandGroup below already
                    // owns bare ⌘=/⌘−/⌘0; this monitor exists only to catch
                    // ⌘⇧= (what a US keyboard sends for "⌘+"), which no
                    // single `keyboardShortcut` can express alongside ⌘=
                    // without two "Zoom In" menu rows. Guarded so a second
                    // `.onAppear` (e.g. the window closing and reopening —
                    // see `enableFirstMouseAcceptance`'s own precedent a few
                    // lines below) never stacks a second monitor.
                    if zoomMonitor == nil {
                        zoomMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
                            guard let action = ZoomKeyRouter.action(
                                characters: event.charactersIgnoringModifiers ?? "",
                                modifiers: event.modifierFlags
                            ) else { return event }
                            switch action {
                            case .zoomIn: CicadaTheme.zoomIn()
                            case .zoomOut: CicadaTheme.zoomOut()
                            case .reset: CicadaTheme.resetZoom()
                            }
                            return nil
                        }
                    }
                    backend.start()
                    // Arms the per-browser watches and catches up on anything
                    // saved while the app was closed.
                    browserWatcher.start(store: store)
                    // When SleepViewModel observes a cycle finish (running ->
                    // idle, no error), refresh the graph/topics layer in
                    // place. Without this, Sleep finishes successfully but
                    // Topics/Graph stay frozen on the pre-cycle snapshot
                    // until the user restarts the app.
                    sleepVM.onCycleCompleted = { [graphVM, inboxVM] in
                        await graphVM.loadGraph()
                        await inboxVM.loadInbox()
                    }
                    // Resolving an inbox item drops the menu-bar badge instantly
                    // instead of waiting for the next 30s status poll.
                    inboxVM.onResolved = { [menuBarManager] in
                        await menuBarManager.refreshAfterAction()
                    }
                    // Ensure the main window is key so TextFields can accept input.
                    if let window = NSApplication.shared.windows.first(where: { $0.canBecomeKey }) {
                        syncWindowChrome(window, mode: appColorScheme)
                        enableFirstMouseAcceptance(for: window)
                        window.makeKeyAndOrderFront(nil)
                    }
                    menuBarManager.setup(
                        onOpenApp: {
                            NSApplication.shared.activate(ignoringOtherApps: true)
                            if let window = NSApplication.shared.windows.first(where: { $0.canBecomeKey }) {
                                window.makeKeyAndOrderFront(nil)
                            }
                        },
                        onRunSleep: {
                            await sleepVM.triggerManually()
                            await menuBarManager.refreshAfterAction()
                        },
                        onSaveClipboardURL: {
                            await menuBarManager.saveClipboardURL()
                        }
                    )

                    // Drive the menu-bar bookworm's stage dots live during a
                    // running cycle (1s cadence), separate from the coarse 30s
                    // poll below. applySleep only touches the sleep sub-struct so
                    // the two never conflict.
                    sleepVM.onStatusChanged = { next in
                        menuBarManager.applySleep(next)
                    }

                    // The menu-bar bookworm is now driven by the Store's status
                    // snapshot (SSE-pushed + refreshed on every version bump)
                    // instead of a 30s poll. The Store tracks the sleep
                    // running -> idle edge itself and hands us the timestamp
                    // that makes the worm `digest`.
                    store.onStatus = { [menuBarManager] snapshot, justFinishedAt in
                        menuBarManager.apply(snapshot: snapshot, justFinishedAt: justFinishedAt)
                    }

                    // Disk first (instant frame), network second, then live.
                    Task { @MainActor in await store.bootstrap() }
                }
                // NOTE: no `.onDisappear` teardown — closing the window must
                // not stop the sync engine. The app lives on in the menu bar,
                // and the bookworm is fed by the Store's status snapshot.
        }
        .defaultSize(width: 1200, height: 800)
        // G130 R5: the View menu — ⌘+/⌘−/⌘0 scale the whole SwiftUI chrome
        // through the one persisted `CicadaTheme.uiScale` (Task 1). Placed
        // `after: .sidebar` so it lands right after macOS's own "Enter Full
        // Screen" section in the View menu, the natural home for view-scale
        // controls. `.keyboardShortcut("=", modifiers: .command)` is what a
        // US keyboard reports for bare ⌘=; ⌘⇧= (what people actually type
        // for "⌘+") is covered by the local key monitor above via
        // `ZoomKeyRouter`, since SwiftUI cannot give one menu item two key
        // equivalents.
        .commands {
            CommandGroup(after: .sidebar) {
                Button("Zoom In") { CicadaTheme.zoomIn() }
                    .keyboardShortcut("=", modifiers: .command)
                Button("Zoom Out") { CicadaTheme.zoomOut() }
                    .keyboardShortcut("-", modifiers: .command)
                Button("Actual Size") { CicadaTheme.resetZoom() }
                    .keyboardShortcut("0", modifiers: .command)
            }
        }

        // ⌘, and the sidebar's footer gear. Gets the same environment as the
        // main window — `ConnectionsView` is a projection over the same Store.
        // `sleepVM` added for the Schedule tab (G106 amendment) — the SAME
        // view model instance the main window's Sleep page uses, so a
        // change made here (or a Pause tap over there) is visible in both
        // without a refetch.
        Settings {
            SettingsScene()
                .environment(connectionsVM)
                .environment(sleepVM)
                .environment(sleepEngineVM)
                .environment(store)
                .preferredColorScheme(appColorScheme == .light ? .light : .dark)
                // The `.id(colorSchemeRaw)` that used to be here is gone with
                // its twin in `ContentView`: `CicadaTheme.mode` is observable
                // now, so this window's own token reads repaint it on a theme
                // flip. The comment it carried — "static reads SwiftUI doesn't
                // track" — described the bug, not a rule.
        }
    }

    /// Keeps the native AppKit window chrome (titlebar material + background)
    /// in lockstep with the SwiftUI theme. NSWindow isn't SwiftUI-observed,
    /// so this must be called explicitly on launch and again on every toggle
    /// (see the `.onChange(of: colorSchemeRaw)` above).
    ///
    /// A transparent titlebar + a matching window background makes the bar
    /// read as a continuation of the app's content on every page instead of
    /// the default gray macOS titlebar material. (A per-page content
    /// background can't recolor window chrome — that was the failed earlier
    /// attempt that also stretched the Inbox window.)
    private func syncWindowChrome(_ window: NSWindow, mode: AppColorScheme) {
        window.titlebarAppearsTransparent = true
        switch mode {
        case .dark:
            window.appearance = NSAppearance(named: .darkAqua)
            window.backgroundColor = NSColor(red: 14 / 255, green: 15 / 255, blue: 20 / 255, alpha: 1)
        case .light:
            window.appearance = NSAppearance(named: .aqua)
            window.backgroundColor = NSColor(red: 245 / 255, green: 246 / 255, blue: 250 / 255, alpha: 1)
        }
    }

    /// Reparents the window's existing (SwiftUI-owned) content view under a
    /// `FirstMouseAcceptingView` wrapper exactly once, preserving frame and
    /// autoresizing so nothing visually shifts, so native controls register
    /// their first click even when the window isn't key yet. Idempotent: a
    /// second call sees `window.contentView` already wrapped and no-ops.
    private func enableFirstMouseAcceptance(for window: NSWindow) {
        guard let hostedContent = window.contentView,
              !(hostedContent is FirstMouseAcceptingView)
        else { return }
        let wrapper = FirstMouseAcceptingView(frame: hostedContent.frame)
        wrapper.autoresizingMask = [.width, .height]
        hostedContent.frame = wrapper.bounds
        hostedContent.autoresizingMask = [.width, .height]
        window.contentView = wrapper
        wrapper.addSubview(hostedContent)
    }
}
