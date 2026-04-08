import SwiftUI

@main
struct CicadaApp: App {
    @State private var graphVM = GraphViewModel()
    @State private var nudgeVM = NudgeViewModel()
    @State private var clarificationVM = ClarificationViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(graphVM)
                .environment(nudgeVM)
                .environment(clarificationVM)
                .preferredColorScheme(.dark)
        }
        .defaultSize(width: 1200, height: 800)
    }
}
