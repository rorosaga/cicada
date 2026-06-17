import SwiftUI
import AppKit

@main
struct CicadaApp: App {
    @State private var graphVM = GraphViewModel()
    @State private var inboxVM = InboxViewModel()
    @State private var sleepVM = SleepViewModel()
    @State private var banksVM = BanksViewModel()
    @State private var menuBarManager = MenuBarManager()
    @State private var backend = BackendProcess()
    @State private var menuPollTask: Task<Void, Never>?

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
                .preferredColorScheme(.dark)
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
                        // Unify the title bar with the dark app background (#0E0F14).
                        // The default macOS titlebar material reads gray over the
                        // app's near-black content; a transparent titlebar + a
                        // matching window background makes the bar consistently dark
                        // on every page. (A per-page content background can't recolor
                        // window chrome — that was the failed earlier attempt that
                        // also stretched the Inbox window.)
                        window.titlebarAppearsTransparent = true
                        window.backgroundColor = NSColor(red: 14 / 255, green: 15 / 255, blue: 20 / 255, alpha: 1)
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
}
