import SwiftUI

@main
struct CicadaApp: App {
    @State private var graphVM = GraphViewModel()
    @State private var nudgeVM = NudgeViewModel()
    @State private var clarificationVM = ClarificationViewModel()
    @State private var menuBarManager = MenuBarManager()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(graphVM)
                .environment(nudgeVM)
                .environment(clarificationVM)
                .preferredColorScheme(.dark)
                .onAppear {
                    menuBarManager.setup {
                        // Bring app window to front
                        NSApplication.shared.activate(ignoringOtherApps: true)
                        if let window = NSApplication.shared.windows.first {
                            window.makeKeyAndOrderFront(nil)
                        }
                    }
                }
        }
        .defaultSize(width: 1200, height: 800)
    }
}
