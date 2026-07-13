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
    @State private var graphVM = GraphViewModel()
    @State private var inboxVM = InboxViewModel()
    @State private var sleepVM = SleepViewModel()
    @State private var banksVM = BanksViewModel()
    @State private var menuBarManager = MenuBarManager()
    @State private var backend = BackendProcess()
    @State private var menuPollTask: Task<Void, Never>?

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
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(graphVM)
                .environment(inboxVM)
                .environment(sleepVM)
                .environment(banksVM)
                .preferredColorScheme(appColorScheme == .light ? .light : .dark)
                .onChange(of: colorSchemeRaw) { _, newValue in
                    let mode = AppColorScheme(rawValue: newValue) ?? .dark
                    CicadaTheme.mode = mode
                    if let window = NSApplication.shared.windows.first(where: { $0.canBecomeKey }) {
                        syncWindowChrome(window, mode: mode)
                    }
                }
                .onAppear {
                    backend.start()
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

                    // Single long-lived 30s poll that drives the tamagotchi and
                    // tracks the running -> idle edge to fire `digesting`.
                    menuPollTask = Task { @MainActor in
                        var wasRunning = false
                        var justFinishedAt: Date? = nil
                        while !Task.isCancelled {
                            if let snap = await StatusService.shared.fetch() {
                                let nowRunning = snap.sleep.status == "running"
                                if wasRunning && !nowRunning { justFinishedAt = Date() }
                                wasRunning = nowRunning
                                menuBarManager.apply(snapshot: snap, justFinishedAt: justFinishedAt)
                            }
                            try? await Task.sleep(for: .seconds(30))
                        }
                    }
                }
                .onDisappear {
                    menuPollTask?.cancel()
                    menuPollTask = nil
                }
        }
        .defaultSize(width: 1200, height: 800)
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
