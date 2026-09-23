import SwiftUI

/// The shell's numbers and its pure decisions (DESIGN_RULES §5.1, §5.5). Views render these;
/// NavRailTests reads them. Every dimension is at uiScale 1 and scales through
/// `CicadaTheme.scaled` (DR-70).
enum ShellMetrics {
    /// R-DS15 — rail or labelled sidebar, per viewer. A convenience, so `UserDefaults`.
    static let labelledKey = "cicada.shell.labelledSidebar"
    static let railWidth: CGFloat = 56
    static let sidebarWidth: CGFloat = 208
    static let railCell: CGFloat = 36          // at a 40 pt pitch (a 4 pt gap)
    static let sidebarRow: CGFloat = 32
    static let railInset: CGFloat = 10         // (56 − 36) / 2
    static let commandBarWidth: CGFloat = 520
    static let commandBarHeight: CGFloat = 32

    static func navWidth(labelled: Bool) -> CGFloat {
        CicadaTheme.scaled(labelled ? sidebarWidth : railWidth)
    }
}

/// One rail cell's words and key — the rail's order is `AppTab.allCases`, which is its ⌘ order.
enum RailItem {
    static func digit(for tab: AppTab) -> Int { (AppTab.allCases.firstIndex(of: tab) ?? 0) + 1 }
    static func key(for tab: AppTab) -> KeyEquivalent { KeyEquivalent(Character(String(digit(for: tab)))) }
    static func shortcut(for tab: AppTab) -> String { "⌘\(digit(for: tab))" }
    static func tooltipTitle(_ tab: AppTab, busy: Bool) -> String {
        busy ? "\(tab.title) · \(Copy.railConsolidating)" : tab.title
    }
    static func accessibilityLabel(_ tab: AppTab, count: Int, busy: Bool) -> String {
        var label = tab.title
        if count > 0 { label += ", \(UsageFormat.count(count)) pending" }
        if busy { label += ", \(Copy.railConsolidating)" }
        return label
    }
}

/// R-DS14 — when a rail tooltip may open.
enum RailTooltipTiming {
    static func delay(lastHiddenAt: Date?, isShowing: Bool, now: Date) -> TimeInterval {
        if isShowing { return 0 }
        if let last = lastHiddenAt, now.timeIntervalSince(last) <= CicadaMotion.railTooltipWarmWindow { return 0 }
        return CicadaMotion.railTooltipDelay
    }
}

/// R-DS20 — the titlebar's items under a modal. The toolbar itself never goes away, so the
/// titlebar never changes height under the person's pointer.
struct ShellChrome: Equatable {
    var welcomeShowing = false
    var settingsOpen = false

    var itemsHidden: Bool { welcomeShowing }
    var itemsDisabled: Bool { welcomeShowing || settingsOpen }
    var itemOpacity: Double { welcomeShowing ? 0 : (settingsOpen ? 0.4 : 1) }
}

extension View {
    func shellChrome(_ chrome: ShellChrome) -> some View {
        opacity(chrome.itemOpacity)
            .disabled(chrome.itemsDisabled)
            .accessibilityHidden(chrome.itemsHidden)
    }
}
