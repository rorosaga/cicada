import SwiftUI

/// The titlebar is a command bar (DR-23), built as a real SwiftUI toolbar so AppKit keeps the
/// drag area, the traffic lights and double-click-to-zoom in every gap (R-DS16): the sidebar
/// toggle after the traffic lights, the command bar centred, the page's `?` at the right.
struct ShellToolbar: ToolbarContent {
    @Binding var labelled: Bool
    /// Which popover the page's `?` opens (R-DS18) — `HelpContent.page(selectedTab)`.
    let help: HelpContent
    let chrome: ShellChrome

    var body: some ToolbarContent {
        ChromeToolbarItem(placement: .navigation) {
            IconButton(systemName: "sidebar.left",
                       help: (labelled ? Copy.showIconRail : Copy.showLabelledSidebar) + " (⌃⌘S)",
                       accessibilityLabel: labelled ? Copy.showIconRail : Copy.showLabelledSidebar,
                       size: .titlebar) { labelled.toggle() }
                .shellChrome(chrome)
        }
        ChromeToolbarItem(placement: .principal) {
            CommandBar().shellChrome(chrome)
        }
        ChromeToolbarItem(placement: .primaryAction) {
            TitlebarHelpButton(content: help).shellChrome(chrome)
        }
    }
}
