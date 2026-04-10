import SwiftUI
import AppKit

@main
struct CicadaApp: App {
    @State private var graphVM = GraphViewModel()
    @State private var nudgeVM = NudgeViewModel()
    @State private var clarificationVM = ClarificationViewModel()
    @State private var sleepVM = SleepViewModel()
    @State private var menuBarManager = MenuBarManager()
    @State private var backend = BackendProcess()

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
                .environment(nudgeVM)
                .environment(clarificationVM)
                .environment(sleepVM)
                .preferredColorScheme(.dark)
                .onAppear {
                    backend.start()
                    // When SleepViewModel observes a cycle finish (running ->
                    // idle, no error), refresh the graph/topics layer in
                    // place. Without this, Sleep finishes successfully but
                    // Topics/Graph stay frozen on the pre-cycle snapshot
                    // until the user restarts the app.
                    sleepVM.onCycleCompleted = { [graphVM] in
                        await graphVM.loadGraph()
                    }
                    // Ensure the main window is key so TextFields can accept input.
                    if let window = NSApplication.shared.windows.first(where: { $0.canBecomeKey }) {
                        window.makeKeyAndOrderFront(nil)
                    }
                    menuBarManager.setup {
                        NSApplication.shared.activate(ignoringOtherApps: true)
                        if let window = NSApplication.shared.windows.first(where: { $0.canBecomeKey }) {
                            window.makeKeyAndOrderFront(nil)
                        }
                    }
                }
        }
        .defaultSize(width: 1200, height: 800)
    }
}
