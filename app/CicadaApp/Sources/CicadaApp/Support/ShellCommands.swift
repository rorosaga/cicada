import SwiftUI

/// The shell's menu commands (R-DS15, R-DS23).
///
/// ⌃⌘S is the system's own "toggle sidebar" shortcut. The toggle goes BEFORE the system's
/// `.sidebar` group rather than replacing it: that group also carries Enter/Exit Full Screen,
/// and replacing it would take full screen out of the View menu. With no `NavigationSplitView`
/// left, the system adds no sidebar item of its own, so the two never double up.
///
/// ⌘, replaces the app menu's Settings… item (DR-33): there is no `Settings{}` scene any more,
/// so the item opens the in-app panel through the one door, `AppRouter.openSettings` (R-DS22).
/// `ShellCommandsTests` keeps the shortcut in this file alone.
struct ShellCommands: Commands {
    let router: AppRouter
    @AppStorage(ShellMetrics.labelledKey) private var labelled = false
    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        // R-OB18 — the AppKit paths (menu bar, Dock opens, reminder taps) open the window through this action when
        // none exists. A value handed over, not state: nothing observes it.
        let _ = router.adoptOpenMainWindow { openWindow(id: CicadaApp.mainWindowID) }
        // R-DS23 — Settings… ⌘, opens the panel inside the main window. With no window open (the
        // app living in the menu bar) it opens one first; the staged request lands when it appears.
        CommandGroup(replacing: .appSettings) {
            Button(Copy.settingsMenuItem) {
                Task { @MainActor in
                    if !router.openSettings() { openWindow(id: CicadaApp.mainWindowID) }
                }
            }
            .keyboardShortcut(",", modifiers: .command)
        }
        CommandGroup(before: .sidebar) {
            Button(labelled ? Copy.showIconRail : Copy.showLabelledSidebar) { labelled.toggle() }
                .keyboardShortcut("s", modifiers: [.control, .command])
        }
    }
}
