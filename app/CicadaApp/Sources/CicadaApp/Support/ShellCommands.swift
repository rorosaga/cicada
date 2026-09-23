import SwiftUI

/// The shell's menu commands (R-DS15; Task 6 adds ⌘,). ⌃⌘S is the system's own "toggle
/// sidebar" shortcut. The toggle goes BEFORE the system's `.sidebar` group rather than
/// replacing it: that group also carries Enter/Exit Full Screen, and replacing it would take
/// full screen out of the View menu. With no `NavigationSplitView` left, the system adds no
/// sidebar item of its own, so the two never double up.
struct ShellCommands: Commands {
    @AppStorage(ShellMetrics.labelledKey) private var labelled = false

    var body: some Commands {
        CommandGroup(before: .sidebar) {
            Button(labelled ? Copy.showIconRail : Copy.showLabelledSidebar) { labelled.toggle() }
                .keyboardShortcut("s", modifiers: [.control, .command])
        }
    }
}
