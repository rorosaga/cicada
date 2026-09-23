import SwiftUI

/// The titlebar is a command bar (DR-23), built as a real SwiftUI toolbar so AppKit keeps the
/// drag area, the traffic lights and double-click-to-zoom in every gap (R-DS16). This task
/// adds the sidebar toggle that follows the traffic lights; Task 4 adds the command bar and
/// the page's `?`.
struct ShellToolbar: ToolbarContent {
    @Binding var labelled: Bool
    let chrome: ShellChrome

    var body: some ToolbarContent {
        ChromeToolbarItem(placement: .navigation) {
            IconButton(systemName: "sidebar.left",
                       help: (labelled ? Copy.showIconRail : Copy.showLabelledSidebar) + " (⌃⌘S)",
                       accessibilityLabel: labelled ? Copy.showIconRail : Copy.showLabelledSidebar,
                       size: .titlebar) { labelled.toggle() }
                .shellChrome(chrome)
        }
    }
}
